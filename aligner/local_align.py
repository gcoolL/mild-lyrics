"""Word timings measured here, on this machine, against the song's own audio.

The program has never been able to hear anything. Every timing in it is
second-hand: the player's clock, or another transcription's stamps grafted onto
our words. That is the ceiling on all of it -- a graft can only cover the lines
somebody else wrote down, and the timing offset has to be inferred from
Spotify's own coarse analysis rather than measured against the song.

Forced alignment lifts that ceiling, because the text is an INPUT. Hand it the
audio and the words on screen and it says where those words are sung -- every
line of them, in our wording, with no second transcription to reconcile.

This used to be a Hugging Face Space: a token to set, a queue to sit in, and a
copy of somebody's record uploaded to a machine we do not own. It all happens
here now, in two stages:

  1. Demucs pulls the vocal out of the mix. The aligner is a speech model being
     asked to listen to a record, and the drums, the bass and the synths are all
     noise to it -- taking them away is the largest single thing that can be
     done for its accuracy. It is also the expensive half by a wide margin.
  2. torchaudio's MMS_FA places our own words inside that vocal.

Both stages want a GPU and neither is allowed to assume it can have one. See
`room()`: each stage says what it needs before it starts, is told how much audio
it may hold at once, and is sent to the CPU when the card is busy with something
else -- a game, another model, a browser. Nothing here takes the last gigabyte
of a card it is sharing, and an out-of-memory error is treated as an
over-estimate to shrink from rather than a crash.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import concurrent.futures
import contextlib
import json
import os
import pathlib
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import unicodedata
import urllib.parse

import genius_roman as GR
import lyric_sources as LS
import spicy_lyrics as SL

MIN_SCORE = 0.005
PACKED_UNDER = 0.1
ONSET_HOP = 160
ONSET_NEAR = 25
ONSET_OVER = 1.4
ONSET_WINDOW = 0.12
ONSET_FORWARD = 0.4
ONSET_DOUBT = 2.0
ONSET_BACK = 5
ONSET_LATE = 0.06
ONSET_LEAD_KEPT = False
HEARD_SHARE = 0.35
HEARD_MARGIN = 0.15
NULL_FLOOR = 0.05
VERIFY_MODEL = "openai/whisper-base"
COMMON = frozenset("""
a an the and or but if so as at by for from in into of off on to up with
i im ive id you youre your yours we were us our they them their he him his
she her it its me my mine myself this that these those there here
is are was were be been being am do does did done doing have has had
will would can could should shall may might must not no nor never
all any both each few more most other some such only own same than too very
what which who whom whose when where why how all just now then out over under
again once about above after before below down during
oh ooh ah aah yeah yea ya na la da uh huh mm hmm ay aye woo
like get got go going gone come came know knows knew let lets
""".split())


class _NoVerdict(Exception):
    """The recording could not be judged, which is not the same as failing."""
MAX_WORD = 4.0


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
UNSPACED = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿가-힣]")
KANA = re.compile(r"[぀-ゟ゠-ヿ]")
ASCII_OK = re.compile(r"^[a-z']+$")

_uroman = None
_kakasi = None
_reading: dict[str, str] = {}


def _romanise(text: str) -> str:
    """`text` in Latin letters, by whatever this machine has to do it with.

    pykakasi first where it applies: it knows which reading a kanji takes in
    context, which uroman cannot, and Japanese is the language this program
    sees most of. uroman for everything else, being the tool MMS_FA's own
    authors used to build the model.
    """
    global _uroman, _kakasi
    if _kakasi is None:
        try:
            import pykakasi
            _kakasi = pykakasi.kakasi()
        except Exception:
            _kakasi = False
    if _kakasi and KANA.search(text):
        try:
            return " ".join(p.get("hepburn") or "" for p in _kakasi.convert(text))
        except Exception:
            pass
    if _uroman is None:
        try:
            import uroman as _u
            _uroman = _u.Uroman()
        except Exception:
            _uroman = False
    if _uroman:
        try:
            return _uroman.romanize_string(text)
        except Exception:
            pass
    return text


def _units(text: str) -> list[tuple[str, bool]]:
    """One line cut into units to be timed. (text, joins the one before it).

    Spaced text splits on the spaces, as it always did. An unspaced run is cut
    by pykakasi where it can be -- it segments Japanese into words, which is the
    unit a reader actually sees -- and per character otherwise, since a hanzi or
    a hangul block is itself about a syllable.

    The flag says the unit follows the last one with no space. That is the
    natural fact to know here, while the line is being cut up, and it is NOT
    what IsPartOfWord means -- that one points the other way, at the next
    syllable. _fill turns one into the other.
    """
    out: list[tuple[str, bool]] = []
    for word in text.split():
        if not UNSPACED.search(word):
            out.append((word, False))
            continue
        if _kakasi and KANA.search(word):
            try:
                got = list(_kakasi.convert(word))
            except Exception:
                got = []
            parts = [p.get("orig") or "" for p in got]
            reads = {p["orig"]: p["hepburn"] for p in got
                     if p.get("orig") and p.get("hepburn")}
            parts = [p for p in parts if p]
            if len(parts) > 1 and "".join(parts) == word:
                _reading.update(reads)
                out += [(p, i > 0) for i, p in enumerate(parts)]
                continue
            _reading.update(reads)
        if len(word) > 1:
            out += [(ch, i > 0) for i, ch in enumerate(word)]
        else:
            out.append((word, False))
    return out


def words_of(doc: dict) -> tuple[list[str], list[tuple[int, int, bool]]]:
    """Every unit in the document, and where each came from.

    The second list is (line index, index within the line, joins the previous),
    so timings can be put back exactly where they were taken from -- which is
    the only reason this can return our own wording rather than the aligner's.
    """
    _reading.clear()
    words: list[str] = []
    where: list[tuple[int, int, bool]] = []
    for li, item in enumerate(LS._items(SL.payload(doc))):
        text = SL.line_text(item) or ""
        _romanise("")
        wi, group = 0, 0
        for chunk, bg in _voices(text):
            at = None
            if bg:
                at = group
                group += 1
            for w, joined in _units(chunk):
                words.append(w)
                where.append((li, wi, joined, at))
                wi += 1
    return words, where


ADLIB = re.compile(r"\(([^()]*)\)")


def _voices(text: str) -> list[tuple[str, bool]]:
    """One line cut into (text, is an ad-lib) runs, in the order it is written.

    The lead and its ad-libs are two voices at once, and the aligner can only
    walk one. Left in the lead's stream an ad-lib is given time of its own,
    which is time the lead is still singing -- "Livin' on hate won't get you
    far (What?)" has to fit the "(What?)" after "far", and the lead's next line
    starts late by however long that took. Cut apart here, timed apart in
    timings(), and put back as a Background group in to_document().

    A line that is nothing BUT an ad-lib -- a whole "(Woah)" on its own line --
    keeps it as the lead. There is no other voice for it to answer, and a line
    with an empty lead has nothing to draw.
    """
    out: list[tuple[str, bool]] = []
    at = 0
    for m in ADLIB.finditer(text):
        if text[at:m.start()].strip():
            out.append((text[at:m.start()], False))
        if m.group(1).strip():
            out.append((m.group(1), True))
        at = m.end()
    if text[at:].strip():
        out.append((text[at:], False))
    if not any(not bg for _t, bg in out):
        return [(text, False)]
    return out or [(text, False)]


TRANSLATION = re.compile(
    r"(\btranslat|\btradu|\bübersetz|\bubersetz|\bvertaling|çeviri|ceviri"
    r"|tłumacz|tlumacz|fordítás|forditas|prijevod|превод|перевод|переклад"
    r"|翻訳|번역|翻译|譯|ترجمة|תרגום)", re.I)


def _same_artist(theirs: str, who: str) -> bool:
    """Two normalised names, judged as the one account or not.

    A plain substring test says "A" is Radiohead, because the single letter
    is inside "radiohead" -- true of the string and false of the world. Below
    a handful of characters a substring proves nothing, so a short name has
    to match exactly; only names long enough to be a real word or two are
    allowed to be a fragment of the other ("blof" of "blofmusic", "coldplay"
    of "coldplayofficial").
    """
    if not theirs or not who:
        return False
    if theirs == who:
        return True
    shorter, longer = (theirs, who) if len(theirs) <= len(who) else (who, theirs)
    return len(shorter) >= 3 and shorter in longer


def _bare(name: str) -> str:
    """A title without the parenthetical Spotify hangs off the end of it.

    "FE!N (feat. Playboi Carti)" searches worse than "FE!N" does, and the
    feature is in the artist field anyway.
    """
    out = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*", " ", name or "")
    out = re.sub(r"\s+-\s+(remaster|remastered|single|radio|album)\b.*$", "", out, flags=re.I)
    return out.strip() or (name or "").strip()


GENIUS_TRIES = 3
GENIUS_WAIT = 0.6


def _genius_hits(token: str, title: str, artist: str, timeout: float) -> list[dict]:
    """Genius search results for a song, plainly.

    Not GR.search(): that one exists to find ROMANISATIONS and its queries say
    so -- it appends "Romanized" and leans on the Genius Romanizations account.
    Asked for FE!N it returned nine transliterated Mandarin songs and no Travis
    Scott at all, which is correct behaviour for its own job and useless here.
    """
    got, seen = [], set()
    first = _bare(title)
    lead = _bare(re.split(r"\s*[,&]\s*|\s+(?:feat|ft|with)\.?\s+", artist or "",
                          maxsplit=1)[0])
    for query in (f"{lead} {first}".strip(), f"{first} {lead}".strip(),
                  f"{first} {_bare(artist)}".strip(), first):
        url = f"{GR.API}/search?{urllib.parse.urlencode({'q': query})}"
        head = {"Authorization": f"Bearer {token}"} if token else {}
        hits = []
        for attempt in range(GENIUS_TRIES):
            try:
                js = json.loads(GR._get(url, head, timeout).decode("utf-8", "replace"))
                hits = (js.get("response") or {}).get("hits") or []
            except Exception:
                hits = []
            if hits:
                break
            if attempt + 1 < GENIUS_TRIES:
                time.sleep(GENIUS_WAIT * (attempt + 1))
        for hit in hits:
            res = hit.get("result")
            if isinstance(res, dict) and res.get("id") and res["id"] not in seen:
                seen.add(res["id"])
                got.append(res)
    return got


ARTIST_MIN = 0.55
TITLE_MIN = 0.55


def _who(hit: dict) -> list[str]:
    """Every name Genius credits on a hit, however it files them.

    All of them, because which field a collaborator lands in is Genius'
    business and not a fact about the song: "GODDESS" has UNBRKBLE in
    primary_artist, ToxiPlays and Kid Wcked in primary_artists, and ImNotAce in
    featured_artists. Asking only the first would have said this is not a
    ToxiPlays song.
    """
    out = [str((hit.get("primary_artist") or {}).get("name") or ""),
           str(hit.get("artist_names") or "")]
    for field in ("primary_artists", "featured_artists"):
        for who in hit.get(field) or []:
            if isinstance(who, dict) and who.get("name"):
                out.append(str(who["name"]))
    return [x for x in out if x.strip()]


def _artist_alike(artist: str, hit: dict) -> float:
    """How well the credits on `hit` match the artist Spotify names. 0..1.

    Every one of ours against every one of theirs, best pair wins. Ours are
    split too: Spotify hands over the whole credit as one string, and a song
    filed on Genius under the second name of four still is that song.
    """
    ours = [artist, _bare(artist)]
    ours += [p for p in re.split(r"\s*[,&]\s*|\s+(?:feat|ft|with)\.?\s+",
                                 artist, flags=re.I) if p.strip()]
    best = 0.0
    for mine in ours:
        for theirs in _who(hit):
            best = max(best, GR.similar(GR.key(_bare(mine)),
                                        GR.key(_bare(theirs))))
    return best


def _translation(hit: dict) -> bool:
    """Is this Genius' translation of the song rather than the song?"""
    if not isinstance(hit, dict):
        return False
    who = str((hit.get("primary_artist") or {}).get("name") or "")
    if re.match(r"\s*genius\b", who, re.I):
        return True
    fields = (str(hit.get("title") or ""), str(hit.get("full_title") or ""),
              str(hit.get("title_with_featured") or ""), who)
    return any(TRANSLATION.search(f) for f in fields)


def genius_doc(token: str, meta: dict, timeout: float = 8.0) -> dict | None:
    """An untimed document of Genius' words for this song, or None.

    Genius is the right source for the TEXT specifically, which is a different
    question from who has the best timings and is why this does not simply use
    the player's chain. That chain ranks by how well a document is timed, so on
    a song nobody has word timing for it will take a line-synced document over
    an unsynced one -- and a line-synced document of the wrong song beats a
    perfect unsynced one. FE!N is the case that showed it: NetEase name-matched
    a Chinese beat listing, "BPM：150 / KEY： / -音名：D", which was line-synced
    and therefore won, and the aligner dutifully timed it.

    Here the timing is about to be measured from the audio, so the only thing
    the text has to be is right. Genius is edited by people who are listening to
    the song, which no other source here can say.
    """
    title = str(meta.get("title") or "").strip()
    artist = str(meta.get("artist") or "").strip()
    if not title:
        return None
    try:
        hits = _genius_hits(token, title, artist, timeout)
    except Exception:
        return None
    best = None
    for hit in hits or []:
        if not GR.is_song(hit) or GR.is_romanization(hit):
            continue
        got = hit.get("result") if isinstance(hit.get("result"), dict) else hit
        if _translation(got):
            continue
        sid = got.get("id")
        if not sid:
            continue
        tsim = GR.similar(GR.key(_bare(title)),
                          GR.key(_bare(str(got.get("title") or ""))))
        if tsim < TITLE_MIN:
            continue
        asim = 1.0
        if artist:
            asim = _artist_alike(artist, got)
            if asim < ARTIST_MIN:
                continue
        score = tsim + asim
        if best is None or score > best[0]:
            best = (score, int(sid))
    if best is None:
        return None
    try:
        marked = GR.voiced_lines(GR.lyrics_for(best[1], timeout=timeout,
                                               markup=True))
    except Exception:
        marked = []
    if not marked:
        try:
            plain = GR.clean_lines(GR.lyrics_for(best[1], timeout=timeout))
        except Exception:
            return None
        marked = [{"text": ln, "who": ""} for ln in plain]
    if len(marked) < 2:
        return None
    flags = GR.sides(marked, main=artist)
    content = []
    for line, opposite in zip(marked, flags):
        item = {"Text": line["text"], "Type": "Vocal"}
        if opposite:
            item["OppositeAligned"] = True
        if line.get("who"):
            item["_who"] = line["who"]
        content.append(item)
    return {"Type": "Static", "_timing": "genius", "Content": content}


HOLD = 0.6

MIN_SYL = 0.02

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
VOICE_HOP = 0.01
VOICE_LEVEL = 0.15
VOICE_QUIET = 0.08
VOICE_MAX = 2.5


LEAD_MIN = 0.35

SUNG_MIN = 0.8
SUNG_SHARE = 0.5
SUNG_LATE = 0.15


def lead_in(wave, rate: int, hop: float = VOICE_HOP) -> float:
    """Seconds of silence before this recording starts, or 0.0.

    The one thing a fetched copy can be wrong about that no amount of alignment
    repairs. Every time this file measures is a time in the FETCHED audio, and
    the player replays it against Spotify's own master -- so a copy that opens
    with two seconds of silence the master does not have puts every line two
    seconds late, uniformly, in an alignment that is internally perfect.
    LENGTH_TOL is 3.0s, so exactly this copy passes the length check.

    Measured on the mix rather than the vocal stem, deliberately: a song that
    opens with eight bars of piano has not started late, and the stem would say
    it had.

    Chroma DTW against the master would answer this better and cannot be run --
    the master is a stream this program cannot open, which is why a copy is
    being fetched in the first place. This is the half of the question that can
    be answered from one file: not "how do these two line up" but "how much of
    this one is nothing".
    """
    try:
        import torch
        x = wave.mean(dim=0) if len(wave.shape) > 1 else wave
        n = max(1, int(hop * rate))
        cut = (x.shape[0] // n) * n
        if cut < n * 10:
            return 0.0
        rms = x[:cut].reshape(-1, n).float().pow(2).mean(dim=1).sqrt()
        db = 20.0 * torch.log10(rms + 1e-9)
        quiet = float(torch.quantile(db, 0.10))
        loud = float(torch.quantile(db, 0.90))
        if not (loud > quiet):
            return 0.0
        thr = quiet + (loud - quiet) * VOICE_LEVEL
        above = (db > thr).nonzero()
        if above.numel() == 0:
            return 0.0
        return float(above[0].item()) * hop
    except Exception:
        return 0.0


class Voice:
    """Where there is a voice in the vocal stem, and where there is not.

    Built once per song from what demucs already produced. Deliberately not a
    model: an RMS envelope and a threshold read off the song's own levels,
    which is all that is wanted here and costs a few milliseconds.
    """

    __slots__ = ("db", "hop", "thr")

    def __init__(self, db, hop: float, thr: float):
        self.db, self.hop, self.thr = db, hop, thr

    @classmethod
    def of(cls, wave, rate: int, hop: float = VOICE_HOP):
        """A Voice for this stem, or None if it cannot be built.

        None is a perfectly good answer and means the caller falls back to
        HOLD -- which is what happens when separation was turned off, or the
        tensor is not one this can do arithmetic on.
        """
        try:
            import torch
            x = wave.mean(dim=0) if len(wave.shape) > 1 else wave
            n = max(1, int(hop * rate))
            cut = (x.shape[0] // n) * n
            if cut < n * 10:
                return None
            rms = x[:cut].reshape(-1, n).float().pow(2).mean(dim=1).sqrt()
            db = 20.0 * torch.log10(rms + 1e-9)
            quiet = float(torch.quantile(db, 0.10))
            loud = float(torch.quantile(db, 0.90))
            if not (loud > quiet):
                return None
            return cls(db, hop, quiet + (loud - quiet) * VOICE_LEVEL)
        except Exception:
            return None

    def until(self, start: float, ceiling: float) -> float:
        """When the voice next goes quiet after `start`, at the latest `ceiling`.

        Quiet means VOICE_QUIET seconds below the threshold together, so a
        consonant's closure inside a held word does not end it.
        """
        need = max(1, int(VOICE_QUIET / self.hop))
        i = max(0, int(start / self.hop))
        stop = min(len(self.db), int(ceiling / self.hop) + need)
        run = 0
        while i < stop:
            if float(self.db[i]) < self.thr:
                run += 1
                if run >= need:
                    return min(ceiling, (i - run + 1) * self.hop)
            else:
                run = 0
            i += 1
        return ceiling


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
VAD_MIN_QUIET = 0.20
VAD_MIN_SPEECH = 0.10

_vad_built: object | None = None


def _vad():
    """Silero's VAD, built once, or False. Small enough to keep."""
    global _vad_built
    if _vad_built is None:
        try:
            from silero_vad import load_silero_vad
            _vad_built = load_silero_vad()
        except Exception:
            _vad_built = False
    return _vad_built


class Speech:
    """Where there are WORDS in the stem, from a model rather than a level.

    Interchangeable with Voice on purpose -- same `until`, same meaning -- so
    everything downstream takes whichever was built without knowing which it
    got, and a machine without silero keeps exactly the behaviour it had.
    """

    __slots__ = ("spans",)

    def __init__(self, spans: list[tuple[float, float]]):
        self.spans = spans

    @classmethod
    def of(cls, wave, rate: int):
        """A Speech for this stem, or None if silero is not there to ask."""
        model = _vad()
        if not model:
            return None
        try:
            import torch
            from silero_vad import get_speech_timestamps
            x = _resample(_channels(wave, 1), rate, RATE)[0].float()
            peak = float(x.abs().max())
            if peak > 0:
                x = x / peak
            with torch.inference_mode():
                got = get_speech_timestamps(
                    x, model, sampling_rate=RATE,
                    min_silence_duration_ms=int(VAD_MIN_QUIET * 1000),
                    min_speech_duration_ms=int(VAD_MIN_SPEECH * 1000))
            spans = [(g["start"] / RATE, g["end"] / RATE) for g in got]
            return cls(spans) if spans else None
        except Exception:
            return None

    def until(self, start: float, ceiling: float) -> float:
        """The end of the phrase `start` falls in, at the latest `ceiling`.

        A word that begins outside any phrase is not held at all -- there is
        nothing being sung for it to be held through.
        """
        for lo, hi in self.spans:
            if hi <= start:
                continue
            if lo > start:
                return start
            return min(ceiling, hi)
        return start

    def since(self, start: float, ceiling: float) -> float:
        """Where singing actually begins at or after `start`, at the latest
        `ceiling` -- or `start` itself if it is already inside a phrase.

        The mirror of `until`, and the half that was missing. `until` stops a
        word being HELD through silence that follows it; nothing asked whether
        a word had begun before anyone was singing. On My Curse the first
        syllable was placed 33.5s in, on something in the intro, and held for
        seventeen seconds until the voice actually arrived -- which trimming
        the end cannot touch, because the end was right and the start was not.
        """
        for lo, hi in self.spans:
            if hi <= start:
                continue
            if lo > start:
                return min(ceiling, lo)
            return start
        return start

    def covered(self, start: float, end: float) -> float:
        """How much of `start`..`end` is inside a phrase, in seconds."""
        total = 0.0
        for lo, hi in self.spans:
            if hi <= start:
                continue
            if lo >= end:
                break
            total += min(end, hi) - max(start, lo)
        return total


def _fill(rows: list[dict], voice: "Voice | None" = None,
          tail: bool = True) -> list[dict]:
    """Give every word in a line a timing, and let each run into the next.

    Two separate repairs, both of them about what CTC does not tell us.

    A word with no span at all is not dropped any more. About 6% of them came
    back untimed -- "I", "it", "and", the short function words whose characters
    a singer runs together -- and dropping them left holes mid-line, with the
    words either side stretched over the space where they should have been.
    Anything untimed is placed between its timed neighbours instead, sharing
    the gap out by how long each word is, which is a guess but a bounded one:
    it cannot move any word outside the interval its neighbours pin down.

    Then every word is run on to meet the next, up to HOLD.
    """
    known = [i for i, r in enumerate(rows) if r["t"] is not None]
    if not known:
        return []
    def spread(idx: list[int], lo: float, hi: float) -> None:
        total = sum(max(1, len(rows[i]["word"])) for i in idx)
        at = lo
        for i in idx:
            take = (hi - lo) * max(1, len(rows[i]["word"])) / total
            rows[i]["t"] = (round(at, 3), round(at + take, 3))
            at += take

    if known[0]:
        edge = rows[known[0]]["t"][0]
        spread(list(range(known[0])), max(0.0, edge - HOLD), edge)
    if known[-1] + 1 < len(rows):
        edge = rows[known[-1]]["t"][1]
        spread(list(range(known[-1] + 1, len(rows))), edge, edge + HOLD)
    for a, b in zip(known, known[1:]):
        if b == a + 1:
            continue
        lo, hi = rows[a]["t"][1], rows[b]["t"][0]
        span = max(0.0, hi - lo)
        gap = rows[a + 1:b]
        total = sum(max(1, len(r["word"])) for r in gap)
        at = lo
        for r in gap:
            take = span * max(1, len(r["word"])) / total
            r["t"] = (round(at, 3), round(at + take, 3))
            at += take
    out = []
    for i, r in enumerate(rows):
        start, end = r["t"]
        limit = rows[i + 1]["t"][0] if i + 1 < len(rows) else end + VOICE_MAX
        if voice is not None:
            end = max(end, min(limit, voice.until(end, end + VOICE_MAX)))
        elif i + 1 < len(rows):
            end = max(end, min(limit, end + HOLD))
        elif tail:
            end = end + min(HOLD, max(0.0, end - start))
        joins = bool(rows[i + 1].get("joined")) if i + 1 < len(rows) else False
        got = {"Text": r["word"], "StartTime": round(start, 3),
               "EndTime": round(max(end, start + MIN_SYL), 3),
               "IsPartOfWord": joins}
        if i + 1 == len(rows):
            got["_measured"] = round(max(r["t"][1], start + MIN_SYL), 3)
        out.append(got)
    return out


def _unoverlap(syls: list[dict], floor: float) -> list[dict] | None:
    """A line that starts before the one above ended, moved out of its way.

    Two lines must not be lit at once, so something has to give when the line
    above overruns. This used to drop every syllable finishing before `floor`
    and keep the remainder:

        keep = [s for s in syls if s["EndTime"] > floor]

    which is a delete, and on a line the aligner had put wholly inside the
    overrun it deleted all but the tail. That is where "Lotta wannabe niggas
    wanna be Lamar" reached the screen as "ar" -- not a line timed wrongly but
    a line taken away, and the words were gone from the TTML altogether.

    A word the model placed is evidence and the overlap is a symptom of the
    line ABOVE being stretched, so the words are kept and the line is squeezed
    into what room is left instead. Everything before `floor` is shared out
    over the gap between `floor` and where the line was already going to end,
    in proportion to how long each syllable is -- the same rule _fill uses for
    a run of untimed words, and bounded the same way: nothing moves outside the
    interval it was already in.

    Where there is no room at all -- the line above ran clean past the end of
    this one -- the line is left untimed rather than crushed into a millisecond
    per syllable. It keeps its words that way, and an untimed line is a thing
    the player already knows how to draw; a line of forty flashes is not.
    """
    late = [s for s in syls if s["StartTime"] >= floor]
    room = (late[0]["StartTime"] if late else syls[-1]["EndTime"]) - floor
    early = [s for s in syls if s["StartTime"] < floor]
    if room < MIN_SYL * len(early):
        return None
    total = sum(max(MIN_SYL, s["EndTime"] - s["StartTime"]) for s in early)
    at = floor
    for s in early:
        take = room * max(MIN_SYL, s["EndTime"] - s["StartTime"]) / total
        s["StartTime"] = round(at, 3)
        s["EndTime"] = round(max(at + take, at + MIN_SYL), 3)
        at += take
    return syls


def _syllables(words: list[str], where: list[tuple[int, int, bool, bool]],
               timed: dict[int, dict], li: int,
               voice: "Voice | None" = None,
               want_bg: int | None = None) -> list[dict] | None:
    """The syllables for one line, in order, or None if nothing landed.

    One voice at a time: `want_bg` is None for the lead and an ad-lib group's
    number for an ad-lib. Each is filled and held on its own, because each is
    separately sung.
    """
    rows = []
    for n, (line, _wi, joined, bg) in enumerate(where):
        if line != li or bg != want_bg:
            continue
        t = timed.get(n)
        parts = (t or {}).get("parts")
        if parts:
            for k, (text, a, b) in enumerate(parts):
                rows.append({"word": text, "joined": joined if k == 0 else True,
                             "t": (a, b)})
            continue
        rows.append({"word": words[n], "joined": joined,
                     "t": (t["start"], t["end"]) if t else None})
    if not rows or not any(r["t"] for r in rows):
        return None
    return _fill(rows, voice, tail=want_bg is None) or None


def _share_gaps(out: list[dict], duration: float | None = None) -> int:
    """Give a line neither model placed the gap between the two that were. How many.

    The last resort, and the only thing in this file that is frankly a guess.
    Everything above is a measurement -- CTC against the audio, or the speech
    model against the same audio -- and a line that has come this far is one
    both of them missed.

    What is still known about it is real, though, and it is not nothing: which
    lines it falls between, and that those two are measured. A run of lines
    inside a measured gap can be shared out across it by how long each line is,
    which is precisely the rule _fill already applies to a run of untimed WORDS
    inside a line. Same bound, too: nothing can land outside the interval its
    neighbours pin down, so a bad guess is bad by less than the gap.

    Where this earns its keep is the repeated hook. "Talk your shit, Tox" is
    eight identical consecutive lines here, and identical lines are exactly
    what neither a CTC walk nor a sequence match can tell apart -- there is no
    evidence in the text saying which repeat is which, only that there are
    eight of them between 1:44 and 1:50. Sharing that stretch evenly is not
    what the singer did to the millisecond, and it is much closer than leaving
    a fifth of the song dark.

    The two ends of the song have only one measured side, and take the song's
    own edges as the other: nothing is sung before 0 or after the last sample,
    so those are bounds rather than inventions. A trailing line shared across
    an outro that turns out to be instrumental is the worst this can do, and it
    is still bounded by the end of the file.

    Refused where the gap is too small to sing in.
    """
    def at(i: int, key: str):
        got = out[i].get(key)
        return float(got) if isinstance(got, (int, float)) else None

    lit = [i for i in range(len(out)) if at(i, "StartTime") is not None]
    if not lit:
        return 0
    done = 0
    stretches = [(a, b, at(a, "EndTime") or at(a, "StartTime"), at(b, "StartTime"))
                 for a, b in zip(lit, lit[1:])]
    if lit[0] > 0:
        stretches.insert(0, (-1, lit[0], 0.0, at(lit[0], "StartTime")))
    if lit[-1] < len(out) - 1 and duration:
        stretches.append((lit[-1], len(out),
                          at(lit[-1], "EndTime") or at(lit[-1], "StartTime"),
                          float(duration)))
    for a, b, lo, hi in stretches:
        run = list(range(a + 1, b))
        if not run or lo is None or hi is None:
            continue
        span = hi - lo
        if span < MIN_SYL * len(run):
            continue
        weight = [max(1, len(SL.line_text(out[i]) or "")) for i in run]
        total = sum(weight)
        edge = lo
        for i, w in zip(run, weight):
            take = span * w / total
            out[i]["StartTime"] = round(edge, 3)
            out[i]["EndTime"] = round(edge + take, 3)
            edge += take
            done += 1
    return done


def to_document(doc: dict, words: list[str],
                where: list[tuple[int, int, bool, bool]],
                result: dict | None,
                voice: "Voice | None" = None,
                spoken: dict[int, tuple[float, float]] | None = None
                ) -> dict | None:
    """A syllable-timed document in OUR words, timed by the alignment.

    Lines the aligner could not place fall back to `spoken` -- where the speech
    model that anchored the walk heard that line -- and failing that keep
    whatever timing they already had, so a partial answer is still worth having
    (the same bargain the graft makes).
    """
    got = (result or {}).get("words") or []
    timed = {}
    for row in got:
        try:
            i = int(row["i"])
            start, end = float(row["start"]), float(row["end"])
        except Exception:
            continue
        if float(row.get("score", 1.0)) < MIN_SCORE:
            continue
        if end <= start or end - start > MAX_WORD:
            continue
        if isinstance(voice, Speech) and end - start > SUNG_MIN:
            sung = voice.covered(start, end)
            if sung < SUNG_SHARE * (end - start):
                began = voice.since(start, end)
                if began - start > SUNG_LATE and end - began >= MIN_SYL * 2:
                    start = began
                end = max(start + MIN_SYL, min(end, voice.until(start, end)))
                if end - start < MIN_SYL * 2:
                    continue
        timed[i] = {"start": round(start, 3), "end": round(end, 3)}
        if row.get("parts"):
            timed[i]["parts"] = row["parts"]
    if not timed:
        return None

    payload = SL.payload(doc)
    items = LS._items(payload)
    out, placed, heard_only = [], 0, 0

    raw = {li: _syllables(words, where, timed, li, voice)
           for li in range(len(items))}

    lit = [li for li in sorted(raw) if raw[li]]
    for a, b in zip(lit, lit[1:]):
        head, tail = raw[b][0]["StartTime"], raw[a][-1]
        stop_at = head if b == a + 1 else min(head, tail.get("_measured", head))
        if tail["EndTime"] > stop_at:
            tail["EndTime"] = round(max(stop_at, tail["StartTime"] + MIN_SYL), 3)
    for syls in raw.values():
        for s in syls or ():
            s.pop("_measured", None)

    floor = 0.0
    for li, item in enumerate(items):
        new = dict(item)
        syls = raw[li]
        if syls and syls[0]["StartTime"] < floor:
            syls = _unoverlap(syls, floor)
        if syls:
            floor = syls[-1]["EndTime"]
            new["Lead"] = {"Syllables": syls,
                           "StartTime": syls[0]["StartTime"],
                           "EndTime": syls[-1]["EndTime"]}
            new["StartTime"] = syls[0]["StartTime"]
            new["EndTime"] = syls[-1]["EndTime"]
            placed += 1
            groups = []
            for gi in sorted({w[3] for w in where
                              if w[0] == li and w[3] is not None}):
                bgs = _syllables(words, where, timed, li, None, want_bg=gi)
                if bgs:
                    for s in bgs:
                        s.pop("_measured", None)
                    groups.append({"Syllables": bgs,
                                   "StartTime": bgs[0]["StartTime"],
                                   "EndTime": bgs[-1]["EndTime"]})
            if groups:
                new["Background"] = groups
                new["StartTime"] = min([new["StartTime"]]
                                       + [g["StartTime"] for g in groups])
                new["EndTime"] = max([new["EndTime"]]
                                     + [g["EndTime"] for g in groups])
                lead_text = ADLIB.sub(" ", SL.line_text(item) or "")
                lead_text = re.sub(r"\s+", " ", lead_text)
                new["Text"] = re.sub(r"\s+([,.!?;:])", r"\1", lead_text).strip()
        elif li in (spoken or {}):
            lo, hi = spoken[li]
            lo, hi = max(lo, floor), max(hi, max(lo, floor) + MIN_SYL)
            nxt = next((raw[n][0]["StartTime"] for n in lit if n > li), None)
            if nxt is not None:
                hi = min(hi, max(lo + MIN_SYL, nxt))
            if hi > lo:
                floor = hi
                new["StartTime"], new["EndTime"] = round(lo, 3), round(hi, 3)
                heard_only += 1
        out.append(new)
    if not placed:
        return None
    shared = _share_gaps(out, (result or {}).get("duration"))
    doc2 = {k: v for k, v in payload.items() if k not in ("Type", "Content", "Lines")}
    doc2["Type"] = "Syllable"
    doc2["Content"] = out
    doc2["_timing"] = "align"
    doc2["_heard_only"] = heard_only
    doc2["_shared"] = shared
    marks = sorted(t for t in (row.get("start") for row in got)
                   if isinstance(t, (int, float)))
    near = sum(1 for a, b in zip(marks, marks[1:]) if b - a < PACKED_UNDER)
    doc2["_packed"] = round(near / max(1, len(marks) - 1), 3)
    scores = [float(row["score"]) for row in got
              if isinstance(row.get("score"), (int, float))]
    doc2["_score"] = round(statistics.median(scores), 5) if scores else 0.0
    got_share = align.overlap
    doc2["_heard_share"] = got_share[0] if isinstance(got_share, tuple) else got_share
    doc2["_heard_null"] = got_share[1] if isinstance(got_share, tuple) else None
    doc2["_snapped"] = getattr(_snap, "found", None)
    doc2["_words"] = getattr(_snap, "total", None)
    agree = getattr(_phone_spans, "gap", None) or []
    doc2["_phone_apart"] = list(getattr(_phone_spans, "apart", None) or [])
    doc2["_phone_gap"] = (round(statistics.median(
        [p - c for _w, c, p in agree]), 3) if agree else None)
    doc2["_phone_seen"] = len(agree)
    doc2["_anchors"] = _anchored.last[0] if _anchored.last else 0
    doc2["_anchor_points"] = list(_anchored.points)
    doc2["_unanchored_why"] = ("" if _anchored.last else
                               (_anchored.why or heard.why or "unknown"))
    return doc2


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
GB = 1024 ** 3

DEMUCS_COST = (1.1, 0.02)
ALIGN_COST = (1.6, 0.08)

DEMUCS_WINDOW = (2.0, 7.8)
ALIGN_WINDOW = (8.0, 30.0)

SPARE = 1.0
CAP_FLOOR = 0.5
CAP_LEAST = 0.05

MODEL = "htdemucs"
RATE = 16000
SEP_RATE = 44100


def _say(log: Callable[[str], Any] | None, msg: str) -> None:
    if log:
        log(msg)


_LOUD = False

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
SPARE_CORES = 2
CPU_RAM_NEEDED = 9.0


def _ram_free() -> float:
    """MemAvailable in GB -- what could be had without swapping. 0 if unknown.

    "Available" rather than "free" on purpose: free memory on a machine that
    has been up a while is nearly zero and says nothing, because the kernel has
    spent it on cache it will hand back on demand.
    """
    try:
        with open("/proc/meminfo", "rb") as fh:
            for line in fh:
                if line.startswith(b"MemAvailable:"):
                    return int(line.split()[1]) * 1024 / GB
    except Exception:
        pass
    return 0.0


def _threads() -> int:
    """How many cores a stage may use, leaving the machine usable.

    Applied per stage rather than once at import: torch is not imported at all
    on the paths that never need it, and a caller who has set its own thread
    count for its own reasons should not be overridden at import time.
    """
    torch = _torch()
    if torch is None:
        return 0
    try:
        want = max(1, (os.cpu_count() or 4) - SPARE_CORES)
        if torch.get_num_threads() > want:
            torch.set_num_threads(want)
        return torch.get_num_threads()
    except Exception:
        return 0


def _rss() -> float:
    """This process's resident memory in GB, or 0 where that cannot be read.

    /proc rather than psutil: it is one read of two integers, it is always
    there on the platform this runs on, and it is not worth a dependency.
    """
    try:
        with open("/proc/self/statm", "rb") as fh:
            pages = int(fh.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / GB
    except Exception:
        return 0.0


def _held() -> float:
    """VRAM this process has taken from the driver, in GB. 0 without a card.

    Our own allocator's reserve, not `survey()`'s free-memory reading: the
    question a debug line answers is "how much of the card is THIS", which the
    free figure cannot say because everything else on the card moves it too.
    """
    torch = _torch()
    if torch is None:
        return 0.0
    try:
        if not torch.cuda.is_available():
            return 0.0
        return torch.cuda.memory_reserved() / GB
    except Exception:
        return 0.0


def _tracing(log: Callable[[str], Any] | None, on: bool):
    """`log`, with the clock and the two memory readings in front of it.

    Every line the aligner already prints, plus a header saying where in the
    run it is and what it is costing -- which is the whole question when a
    stage is slower or heavier than expected, and the answer was previously
    only obtainable by editing this file.
    """
    if not on or log is None:
        return log
    start = time.monotonic()

    def out(msg: str) -> None:
        log(f"[{time.monotonic() - start:6.1f}s  vram {_held():4.1f}G  "
            f"ram {_rss():4.1f}G] {msg}")
    return out


def _torch():
    """The torch module, or None when it is not installed.

    Imported here rather than at the top of the file: it is a second or two and
    a few hundred megabytes, and everything above -- reading the document,
    putting timings back on our lines -- has no use for it.
    """
    try:
        import torch
        return torch
    except ImportError:
        return None


def survey(index: int = 0) -> dict | None:
    """What the card has free right now, in GB, or None if there is no card.

    `mem_get_info` asks the driver rather than our own allocator, so it counts
    what every other process is holding too. That is the entire point: the
    question is not whether a model fits on an idle card, it is whether it fits
    beside whatever is already running on this one.
    """
    torch = _torch()
    if torch is None:
        return None
    try:
        if not torch.cuda.is_available():
            return None
        free, total = torch.cuda.mem_get_info(index)
        name = torch.cuda.get_device_name(index)
    except Exception:
        return None
    return {"name": name, "index": index,
            "free": free / GB, "total": total / GB}


def room(want: str, cost: tuple[float, float], window: tuple[float, float],
         spare: float = SPARE, index: int = 0) -> tuple[str, float, str]:
    """Where a stage should run and how much audio it may hold at once.

    Returns (device, seconds, why). `want` is "auto", "gpu" or "cpu": "auto"
    uses the card only when there is honestly room for it, "gpu" insists and
    accepts the shortest window rather than refusing, "cpu" never looks.

    The CPU is not a failure state. It is three to ten times slower and it
    finishes, which beats taking a card out from under a game.
    """
    lo, hi = window
    if want == "cpu":
        return "cpu", hi, "asked for the CPU"
    got = survey(index)
    if got is None:
        torch = _torch()
        return "cpu", hi, ("torch is not installed" if torch is None
                           else "no CUDA device")
    fixed, per = cost
    spend = got["free"] - spare
    fits = (spend - fixed) / per if per > 0 else hi
    where = f"{got['free']:.1f} of {got['total']:.1f} GB free on {got['name']}"
    if fits < lo:
        if want == "gpu":
            return "cuda", lo, f"{where} -- tight, but the GPU was asked for"
        return "cpu", hi, f"{where} -- not enough for this, so the CPU"
    return "cuda", min(hi, fits), where


def _cap(spare: float = SPARE, index: int = 0) -> None:
    """Hold our own allocator to what was free, less `spare` GB.

    Without this, guessing low means the next allocation comes out of whatever
    else is on the card -- and the process that dies is as likely to be the game
    as it is to be us. With it we hit a ceiling of our own and `_shrinking()`
    takes a smaller window instead. It reads the card again rather than being
    told: the figure `room()` saw is seconds old by now, and the number that
    matters is the one true when the memory is actually taken.
    """
    torch = _torch()
    got = survey(index)
    if torch is None or got is None or got["total"] <= 0:
        return
    spend = max(CAP_FLOOR, got["free"] - spare)
    with contextlib.suppress(Exception):
        torch.cuda.set_per_process_memory_fraction(
            max(CAP_LEAST, min(1.0, spend / got["total"])), index)


class Stopped(Exception):
    """The caller has asked for this alignment to be abandoned.

    Not a failure, and deliberately its own type so it can be told apart from
    one: a stopped job has nothing to report and nothing to remember, where a
    failed job has an error worth showing and a track worth not retrying.
    """


def _stop(stop: Callable[[], bool] | None) -> None:
    """Give up here if the caller has asked us to.

    `stop` is a callable asked between pieces of work rather than a flag read
    once, because the answer changes while the work runs -- that is the entire
    point of it. Where the pieces are long, so is the delay before this bites:
    demucs' apply_model is one call that cannot be interrupted from outside,
    so the finest granularity available is "before the separation" and then
    every window of the two alignment passes, which are seconds apart.
    """
    if stop is not None and stop():
        raise Stopped()


def _oom(exc: BaseException) -> bool:
    """Is this the card saying no? torch.cuda.OutOfMemoryError is a RuntimeError
    and older versions raise a plain one, so the message is what to go on."""
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()


def _shrinking(work, device: str, window: float, span: tuple[float, float],
               log=None, what: str = "") -> object:
    """Run `work(device, window)`, halving the window as the card refuses.

    The estimates above are guesses about hardware this was never run on, so
    being wrong is expected and only the response matters: give the memory back,
    take half as much audio at a time, and when even the smallest window will not
    go, finish the job on the CPU rather than abandoning it.
    """
    lo, hi = span
    torch = _torch()
    while True:
        try:
            return work(device, window)
        except Exception as exc:
            if not _oom(exc) or device == "cpu":
                raise
            if torch is not None:
                with contextlib.suppress(Exception):
                    torch.cuda.empty_cache()
            if window > lo * 1.01:
                window = max(lo, window / 2)
                _say(log, f"  {what}: out of VRAM — retrying "
                          f"{window:.1f}s at a time")
                continue
            _say(log, f"  {what}: out of VRAM at {lo:.1f}s — finishing on the "
                      f"CPU, on {_threads()} of {os.cpu_count()} cores")
            device, window = "cpu", hi


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def _resample(wave, sr: int, rate: int):
    if sr == rate:
        return wave
    import torchaudio
    return torchaudio.functional.resample(wave, sr, rate)


def _channels(wave, want: int):
    """`wave` as (want, samples). Downmix by averaging, upmix by copying."""
    have = wave.shape[0]
    if have == want:
        return wave
    if want == 1:
        return wave.mean(dim=0, keepdim=True)
    if have == 1:
        return wave.repeat(want, 1)
    return wave[:want]


def _read(path: str):
    """(wave, rate) from a file, whatever container it is in.

    soundfile first, because it is already a dependency of the aligner and needs
    no subprocess. ffmpeg second, for the formats libsndfile will not open --
    which on a file the user passed in by hand is most likely to be an mp3 or an
    m4a. torchaudio.load is deliberately not used at all: it dispatches to an
    audio backend it does not itself install, so it raises ImportError at the
    first call rather than at import, which makes a missing dependency look like
    a broken file.
    """
    import torch
    try:
        import soundfile
        data, sr = soundfile.read(path, dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), int(sr)
    except Exception:
        pass
    if not shutil.which("ffmpeg"):
        raise RuntimeError(f"cannot read {os.path.basename(path)}: "
                           f"soundfile refused it and ffmpeg is not on PATH")
    tmp = os.path.join(tempfile.gettempdir(), f"mild-read-{os.getpid()}.wav")
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                        "-i", path, "-ac", "2", "-ar", str(SEP_RATE), tmp],
                       capture_output=True, timeout=900, check=True)
        import soundfile
        data, sr = soundfile.read(tmp, dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), int(sr)
    finally:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def _write(path: str, wave, rate: int) -> None:
    import soundfile
    soundfile.write(path, wave.T.cpu().numpy(), rate)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def separate(wave, rate: int, device: str, window: float,
             name: str = MODEL, log=None, stop=None):
    """The vocal stem of `wave` (channels, samples), at demucs' own rate.

    The model is loaded, used and dropped inside this call. Holding it for a
    second song would save thirty seconds and cost a gigabyte of VRAM that the
    aligner is about to want -- the two stages must not be resident together,
    which is the reason this returns a tensor rather than a loaded model.
    """
    torch = _torch()
    try:
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
    except ImportError:
        return _separate_cli(wave, rate, device, name, log)

    model = get_model(name)
    model.eval()
    wave = _channels(_resample(wave, rate, model.samplerate), model.audio_channels)
    window = min(window, float(getattr(model, "segment", DEMUCS_WINDOW[1]) or
                               DEMUCS_WINDOW[1]))
    ref = wave.mean(dim=0)
    mix = (wave - ref.mean()) / (ref.std() + 1e-8)

    def work(dev, seg):
        _stop(stop)
        _say(log, f"  demucs {name} on {dev}, {seg:.1f}s at a time")
        kw = dict(device=dev, split=True, overlap=0.25, shifts=0, progress=False)
        try:
            got = apply_model(model, mix[None], segment=seg, **kw)
        except TypeError:
            with contextlib.suppress(Exception):
                model.segment = seg
            got = apply_model(model, mix[None], **kw)
        return got[0]

    try:
        out = _shrinking(work, device, window, DEMUCS_WINDOW, log, "demucs")
        out = out * (ref.std() + 1e-8) + ref.mean()
        try:
            vocals = out[list(model.sources).index("vocals")]
        except ValueError:
            raise RuntimeError(f"{name} has no vocal stem: {list(model.sources)}")
        return vocals.clone(), model.samplerate
    finally:
        del model
        if torch is not None:
            with contextlib.suppress(Exception):
                torch.cuda.empty_cache()


def _separate_cli(wave, rate: int, device: str, name: str, log=None):
    """Demucs as a command, for a machine where it was installed as one.

    pipx and friends put the command on PATH without putting the library where
    anything can import it, which is a perfectly reasonable way to have demucs
    installed and a useless one for the call above. The trade is control: the
    command does not expose how much audio it holds at once, so this path can
    choose the device and nothing else, and `room()` has already decided the
    GPU either has space for a full-length window or is not being used.
    """
    exe = shutil.which("demucs")
    if not exe:
        raise RuntimeError(
            "demucs is not installed -- neither the library nor the command.\n"
            "        pip install --user demucs")
    work = tempfile.mkdtemp(prefix="mild-demucs-")
    src = os.path.join(work, "mix.wav")
    try:
        _write(src, _channels(wave, 2), rate)
        _say(log, f"  demucs {name} on {device}, as a subprocess")
        got = subprocess.run(
            [exe, "-n", name, "--two-stems", "vocals", "-d", device,
             "-o", work, "--filename", "{stem}.{ext}", src],
            capture_output=True, text=True, timeout=3600)
        out = os.path.join(work, name, "vocals.wav")
        if got.returncode != 0 or not os.path.exists(out):
            why = (got.stderr or got.stdout or "").strip().splitlines()
            raise RuntimeError("demucs failed: " + (why[-1] if why else "no output"))
        return _read(out)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
KEEP = re.compile(r"[^a-z']")

_built: tuple | None = None


def _flat(word: str) -> str:
    """A word as the aligner spells it: unaccented, lowercase, letters only."""
    s = unicodedata.normalize("NFKD", word)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("’", "'").replace("‘", "'")
    got = KEEP.sub("", s)
    if got or not word.strip():
        return got
    plain = unicodedata.normalize("NFKD", _reading.get(word) or _romanise(word))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return KEEP.sub("", plain.lower().replace("’", "'"))


def _mms():
    """MMS_FA, built once. About 1.2 GB the first time, from PyTorch's own host.

    Built on the CPU and moved per call. The model is the smaller half of this
    file's memory use; the emission is the larger, and that is what the window
    below is for.
    """
    global _built
    if _built is None:
        import torchaudio
        bundle = torchaudio.pipelines.MMS_FA
        _built = (bundle, bundle.get_model(), bundle.get_tokenizer(),
                  bundle.get_aligner())
    return _built


_w2v_built: tuple | None = None


def _w2v():
    """WAV2VEC2_ASR_BASE_960H, wearing MMS_FA's interface.

    An English ASR bundle rather than a forced-alignment one, so it brings a
    model and a label set and nothing else -- the tokenizer and the aligner are
    built here to the same shape MMS_FA hands back, which is the whole point:
    timings() should not know which of the two it is walking.

    Here to be compared, not because it is better. It is what an earlier
    program of this user's aligned with, and the only real difference left
    between that program and this one once the dead code in it is discounted.
    Two things follow from it being an ASR head: the labels are English letters
    only, so it has nothing to say about a Japanese lyric that MMS_FA romanises
    and reads; and the model returns logits where MMS_FA returns log
    probabilities, which is what _logits() is for.
    """
    global _w2v_built
    if _w2v_built is None:
        import torch
        import torchaudio
        bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
        labels = bundle.get_labels()
        ids = {l.lower(): i for i, l in enumerate(labels)}

        def tokenizer(words):
            return [[ids[c] for c in w if c in ids] for w in words]

        def aligner(emission, tokens):
            flat = [t for w in tokens for t in w]
            if not flat:
                return [[] for _ in tokens]
            targets = torch.tensor([flat], dtype=torch.int32)
            got, scores = torchaudio.functional.forced_align(
                emission[None], targets, blank=0)
            spans = torchaudio.functional.merge_tokens(got[0], scores[0].exp(),
                                                       blank=0)
            if len(spans) != len(flat):
                raise RuntimeError(
                    f"{len(spans)} spans for {len(flat)} tokens")
            out, at = [], 0
            for w in tokens:
                out.append(list(spans[at:at + len(w)]) if w else [])
                at += len(w)
            return out

        _w2v_built = (bundle, bundle.get_model(), tokenizer, aligner)
    return _w2v_built


def _emission(model, wave, device: str, window: float, log=None,
              what: str = "aligning", stop=None):
    """Frame-by-frame log probabilities for the whole song, in windows.

    A four-minute song is nearly four million samples, and self-attention over
    that in one go wants tens of gigabytes on any card -- this is the stage that
    would have made a local aligner impossible without cutting it up.

    The cut is overlapped and the overlap is thrown away: each window is run
    with a second of context on either side and only its own middle is kept, so
    a word sitting on a seam is still seen with what came before it. What comes
    back is one emission for the whole song, which the aligner can then walk in
    a single pass -- the alternative, aligning each window against its own slice
    of the text, needs to know where to cut the text, which is the very thing
    being worked out.
    """
    import torch
    n = wave.shape[1]
    step = max(1, int(window * RATE))
    pad = int(min(1.0, window / 4) * RATE)
    parts, at = [], 0
    while at < n:
        _stop(stop)
        lo = max(0, at - pad)
        hi = min(n, at + step + pad)
        with torch.inference_mode():
            got, _ = model(wave[:, lo:hi].to(device))
        got = got[0].float().cpu()
        per = (hi - lo) / max(1, got.shape[0])
        a = int(round((at - lo) / per))
        b = int(round((min(n, at + step) - lo) / per))
        parts.append(got[a:max(a + 1, b)])
        at += step
        if len(parts) % (1 if _LOUD else 4) == 0:
            _say(log, f"  {what}… {min(at, n) / RATE:.0f}s of {n / RATE:.0f}s")
    out = torch.cat(parts, dim=0) if len(parts) > 1 else parts[0]
    return out, n / RATE / max(1, out.shape[0])


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
ANCHOR_MIN = 6
ANCHOR_TOL = 1.5
ANCHOR_SHARE = 0.6
ANCHOR_AGREE = 0.75
ANCHOR_SHIFT = 2.0
ANCHOR_AGREE_MIN = 3
ANCHOR_SQUEEZE = 0.5


class _Span:
    """A token span in absolute frames. What the aligner returns, moved.

    Segments are aligned against their own slice of the emission, so the spans
    come back counted from the slice's start and have to be put back on the
    song's own frame numbering before anything else reads them.
    """
    __slots__ = ("start", "end", "score")

    def __init__(self, start, end, score):
        self.start, self.end, self.score = start, end, score


def _anchor_points(doc: dict, donor: dict, mine: dict[int, float],
                   log: Callable[[str], Any] | None = None
                   ) -> list[tuple[int, float]]:
    """[(line index, when it starts on OUR clock)] from a line-synced donor.

    `mine` is what the first pass measured, and is used for one thing only:
    working out the constant between the donor's clock and this recording's.
    """
    try:
        base = LS._items(SL.payload(doc))
        dit = LS._items(SL.payload(donor))
    except Exception:
        return []
    if not base or not dit:
        return []
    try:
        pairs = LS._pair(base, dit)
    except Exception:
        return []
    if not pairs:
        return []
    delta, when = [], {}
    for i, j in pairs.items():
        d = SL.line_start(dit[j])
        if not isinstance(d, (int, float)):
            continue
        when[i] = float(d)
        s = mine.get(i)
        if isinstance(s, (int, float)):
            delta.append(float(d) - float(s))
    if len(delta) < ANCHOR_MIN or len(when) < ANCHOR_MIN:
        _say(log, f"  only {len(when)} line(s) matched a line-synced copy — "
                  f"aligning the whole song in one pass")
        return []
    delta.sort()
    shift = delta[len(delta) // 2]
    agree = sum(1 for x in delta if abs(x - shift) <= ANCHOR_TOL)
    if agree < ANCHOR_MIN or agree < ANCHOR_SHARE * len(delta):
        _say(log, f"  a line-synced copy matched the words but not the clock "
                  f"({agree} of {len(delta)} lines agree) — it is timed against "
                  f"another edit, so one pass")
        return []
    return sorted((i, when[i] - shift) for i in when)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
ASR_MODEL = "openai/whisper-small"
ASR_COST = (1.9, 0.021)
ASR_WINDOW = (30.0, 120.0)
ASR_CHUNK = 120.0
ASR_OVERLAP = 2.0

_asr_built: dict = {}


def _asr(model: str | None = None):
    """Whisper and its pipeline, built once per model name, or False.

    About 1 GB the first time, from Hugging Face's host -- the same bargain
    _phone_ctc() makes, and it fails the same way: a half-arrived download
    leaves this False and the caller carries on without anchors.

    Keyed by name rather than a single slot, so trying a bigger model against a
    song and then going back does not pay for the download twice. The weights
    of each stay in memory once built, which is why the caller is given a way
    to drop them -- see release().
    """
    name = model or ASR_MODEL
    if name not in _asr_built:
        try:
            from transformers import pipeline
            _asr_built[name] = pipeline("automatic-speech-recognition",
                                        model=name, chunk_length_s=30,
                                        device=-1)
            _asr.last_error = ""
        except Exception as exc:
            _asr.last_error = f"{type(exc).__name__}: {exc}"
            _asr_built[name] = False
    return _asr_built[name]


_asr.last_error = ""


def release() -> None:
    """Drop every model this file is holding, and the VRAM behind them.

    Each stage caches its weights so a second song does not pay to load them
    again, which is right for the player -- it aligns whatever comes on for as
    long as it is open -- and wrong for one run of the command line, where
    three models' weights sit in memory long after their stage has finished.
    Nothing here is needed to READ an answer that has already been returned.
    """
    global _built, _phone_built
    _built = None
    _phone_built = None
    _asr_built.clear()
    torch = _torch()
    if torch is not None:
        with contextlib.suppress(Exception):
            torch.cuda.empty_cache()


def heard(wave, rate: int, device: str, log=None, stop=None,
          model: str | None = None, on_cpu: bool = False,
          chunk: float = ASR_CHUNK) -> list[dict]:
    """[{"word", "start"}] as the model heard this audio. Empty if it could not.

    Never raises: anchors are an improvement on a pass that already works, so
    everything here degrades to "no anchors" rather than to no alignment.
    """
    import torch
    name = model or ASR_MODEL
    pipe = _asr(name)
    if not pipe:
        _say(log, f"  {name} could not be loaded ({_asr.last_error or 'no reason given'})"
                  f" — one pass")
        heard.why = f"{name} could not be loaded"
        return []
    _stop(stop)
    wave = _resample(_channels(wave, 1), rate, RATE)
    audio = wave[0].numpy().astype("float32")
    got = None
    ladder = [device]
    if device != "cpu" and on_cpu:
        ladder.append("cpu")
    elif device != "cpu":
        ladder.append(None)
    for dev in ladder:
        if dev is None:
            _say(log, "  no room on the card for the speech model, and the "
                      "processor would take minutes — going on without anchors "
                      "(--asr-cpu to run it there anyway)")
            heard.why = heard.why or "no room on the card for the speech model"
            break
        if dev == "cpu":
            spare = _ram_free()
            if spare and spare < CPU_RAM_NEEDED:
                _say(log, f"  the speech model wants about "
                          f"{CPU_RAM_NEEDED:.0f} GB on the processor and there "
                          f"is {spare:.1f} GB to be had — going on without "
                          f"anchors")
                break
        try:
            pipe.model.to(dev)
            pipe.device = torch.device(dev)
            if dev != "cpu":
                pipe.model.half()
            else:
                pipe.model.float()
            note = ""
            if dev == "cpu":
                note = f", on {_threads()} of {os.cpu_count()} cores — " \
                       f"this takes minutes"
            secs = len(audio) / float(RATE)
            span = max(ASR_WINDOW[0], min(ASR_CHUNK, float(chunk)))
            _say(log, f"  {name.split('/')[-1]} on {dev}, listening for "
                      f"where the words fall{note}"
                      + (f", {span:.0f}s at a time" if secs > span else ""))
            got = {"chunks": []}
            step = int(span * RATE)
            pad = int(ASR_OVERLAP * RATE)
            at = 0
            while at < len(audio):
                _stop(stop)
                hi = min(len(audio), at + step + pad)
                with torch.inference_mode():
                    part = pipe(audio[at:hi], return_timestamps="word",
                                generate_kwargs={"task": "transcribe"})
                edge = at / RATE
                for c in (part or {}).get("chunks") or []:
                    ts = list(c.get("timestamp") or ()) + [None, None]
                    if not isinstance(ts[0], (int, float)):
                        continue
                    start = float(ts[0]) + edge
                    if at and start < edge + ASR_OVERLAP / 2:
                        continue
                    end = (float(ts[1]) + edge
                           if isinstance(ts[1], (int, float)) else start)
                    got["chunks"].append({"text": c.get("text"),
                                          "timestamp": (start, end)})
                at += step
                if len(audio) > step:
                    _say(log, f"  listening… {min(at, len(audio)) / RATE:.0f}s "
                              f"of {secs:.0f}s")
            break
        except Stopped:
            raise
        except Exception as exc:
            nxt = ladder[ladder.index(dev) + 1:]
            _say(log, f"  the speech model could not run on the {dev} "
                      f"({type(exc).__name__})"
                      + (" — trying the CPU" if "cpu" in nxt else
                         " — going on without anchors"))
            heard.why = f"the speech model failed on the {dev}"
            if dev != "cpu":
                with contextlib.suppress(Exception):
                    torch.cuda.empty_cache()
        finally:
            with contextlib.suppress(Exception):
                pipe.model.to("cpu").float()
                pipe.device = torch.device("cpu")
    if got is None:
        heard.why = heard.why or "the speech model did not run"
        return []
    out = []
    for chunk in (got or {}).get("chunks") or []:
        at, till = (list(chunk.get("timestamp") or ()) + [None, None])[:2]
        text = str(chunk.get("text") or "")
        if isinstance(at, (int, float)) and text.strip():
            out.append({"word": text.strip(), "start": float(at),
                        "end": float(till) if isinstance(till, (int, float))
                        else float(at)})
    return out


def _model_lines(doc: dict, said: list[dict]
                 ) -> tuple[dict[int, float], dict[int, tuple[float, float]]]:
    """({line: where it starts}, {line: (start, end)}), as the model heard it.

    Both come from one sequence match, and the two are used for quite different
    things -- the starts pin the CTC walk (_model_points), and the spans are
    the last resort for a line CTC never placed at all (to_document). Kept
    together because the match is the expensive part and the answer is the
    same match read twice.

    The match is a sequence alignment over the two word streams, not a search
    per line: a line's own words are ambiguous on a song that repeats them --
    "Talk your shit, Tox" is eight consecutive lines here -- and only their
    ORDER tells the repeats apart. SequenceMatcher keeps that order by
    construction, so the fourth "Talk your shit, Tox" can only match the fourth
    time it was heard.
    """
    from difflib import SequenceMatcher
    if not said:
        return {}, {}
    try:
        words, where = words_of(doc)
    except Exception:
        return {}, {}
    if not words:
        return {}, {}
    ours = [_flat(w) for w in words]
    theirs = [_flat(w["word"]) for w in said]
    sm = SequenceMatcher(None, ours, theirs, autojunk=False)
    pairs = {i + k: j + k
             for i, j, n in sm.get_matching_blocks() for k in range(n)
             if ours[i + k]}
    first: dict[int, float] = {}
    span: dict[int, tuple[float, float]] = {}
    for n, (line, _wi, _joined, bg) in enumerate(where):
        if n not in pairs or bg is not None:
            continue
        heard_word = said[pairs[n]]
        if line not in first:
            first[line] = heard_word["start"]
            span[line] = (heard_word["start"], heard_word["end"])
        else:
            span[line] = (span[line][0], max(span[line][1], heard_word["end"]))
    return first, span


def _model_points(doc: dict, said: list[dict],
                  log=None) -> list[tuple[int, float]]:
    """[(line index, when it starts)] by matching our words to what was heard.

    The match is a sequence alignment over the two word streams, not a search
    per line: a line's own words are ambiguous on a song that repeats them --
    "Talk your shit, Tox" is eight consecutive lines here -- and only their
    ORDER tells the repeats apart. SequenceMatcher keeps that order by
    construction, so the fourth "Talk your shit, Tox" can only match the fourth
    time it was heard.
    """
    first, _spans = _model_lines(doc, said)
    if not first:
        _say(log, "  the speech model heard nothing this document says — "
                  "one pass")
        return []
    if len(first) < ANCHOR_MIN:
        _say(log, f"  only {len(first)} line(s) placed by the speech model — "
                  f"one pass")
        return []
    out: list[tuple[int, float]] = []
    for line in sorted(first):
        if not out or first[line] > out[-1][1]:
            out.append((line, first[line]))
    try:
        total = len(LS._items(SL.payload(doc)))
    except Exception:
        total = 0
    _say(log, f"  {len(out)} of {total} lines placed by the speech model"
              + (f" ({len(first) - len(out)} dropped for going backwards)"
                 if len(first) > len(out) else ""))
    return out


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
LINE_PAD = 1.5
LINE_TOUCH = 5


ADLIB_REACH = 3.0


def _per_line(spans, aligner, tokenizer, emission, flat, keep, where,
              per_frame: float, heard: dict | None, log=None):
    """Every line timed on its own, then overlapping pairs timed together.

    `spans` is the walk's answer, used for where to look rather than for the
    times themselves. Returns spans in the same shape, or None if this could
    not be done at all -- in which case the walk's own answer stands.
    """
    lines: dict[int, list[int]] = {}
    for n in range(len(flat)):
        lines.setdefault(where[keep[n]][0], []).append(n)
    order = sorted(lines)
    if len(order) < 2:
        return None
    frames = emission.shape[0]
    heard = heard or {}

    est: dict[int, int] = {}
    for li in order:
        at = heard.get(li)
        if isinstance(at, (int, float)):
            est[li] = max(0, int(at / per_frame))
        else:
            got = [spans[n][0].start for n in lines[li] if spans[n]]
            est[li] = min(got) if got else 0
    lit = [sp for sp in spans if sp]
    pace = ((max(sp[-1].end for sp in lit) - min(sp[0].start for sp in lit))
            / max(1, sum(len(x) for x in flat))) if lit else 1.0
    pad = max(1, int(LINE_PAD / per_frame))

    def walk(ns, f0, f1):
        """Time `ns` inside f0..f1, on the song's own frame numbering."""
        f0 = max(0, min(f0, frames - 1))
        f1 = min(frames, max(f1, f0 + 1))
        piece = [flat[n] for n in ns]
        if f1 - f0 < sum(len(x) for x in piece):
            return None
        try:
            got = aligner(emission[f0:f1], tokenizer(piece))
        except Exception:
            return None
        if len(got) != len(ns):
            return None
        return [[_Span(s.start + f0, s.end + f0, s.score) for s in sp]
                if sp else sp for sp in got]

    out = list(spans)
    placed: dict[int, list] = {}
    for k, li in enumerate(order):
        ns = lines[li]
        need = sum(len(flat[n]) for n in ns)
        nxt = est[order[k + 1]] if k + 1 < len(order) else frames
        f0 = est[li] - pad
        f1 = min(max(nxt, f0 + need), est[li] + int(need * pace * 2) + pad)
        got = walk(ns, f0, f1)
        if got is None:
            continue
        placed[li] = got
        for n, sp in zip(ns, got):
            out[n] = sp

    if not placed:
        return None

    fixed = 0
    done = [li for li in order if li in placed]
    for a, b in zip(done, done[1:]):
        left = [sp for sp in (out[n] for n in lines[a]) if sp]
        right = [sp for sp in (out[n] for n in lines[b]) if sp]
        if not left or not right:
            continue
        if left[-1][-1].end <= right[0][0].start + LINE_TOUCH:
            continue
        ns = lines[a] + lines[b]
        f0 = min(left[0][0].start, right[0][0].start) - pad
        f1 = max(left[-1][-1].end, right[-1][-1].end) + pad
        got = walk(ns, f0, f1)
        if got is None:
            continue
        for n, sp in zip(ns, got):
            out[n] = sp
        fixed += 1
    _say(log, f"  timed {len(placed)} line(s) one at a time, "
              f"{fixed} overlapping pair(s) settled together")
    return out


def _anchored(spans, aligner, tokenizer, emission, flat, keep, where,
              per_frame: float, anchor, log=None):
    """`spans` again, but walked in segments between anchors. None if not done.

    Every failure here returns None and leaves the single-pass answer standing.
    An anchored walk that could not be built is not worth a worse alignment.
    """
    mine: dict = {}
    for n, span in enumerate(spans):
        if not span:
            continue
        line = where[keep[n]][0]
        at = span[0].start * per_frame
        if line not in mine or at < mine[line]:
            mine[line] = at
    try:
        pts = anchor(mine)
    except Exception as exc:
        _say(log, f"  the anchors could not be worked out "
                  f"({type(exc).__name__}: {exc}) — one pass")
        _anchored.why = f"anchors could not be worked out ({type(exc).__name__})"
        return None
    if not pts:
        _anchored.why = "the model offered no anchor points"
        return None

    apart = [(line, at, at - mine[line]) for line, at in pts if line in mine]
    middle = statistics.median([d for _l, _a, d in apart]) if apart else 0.0
    if abs(middle) > ANCHOR_SHIFT:
        _anchored.why = (f"anchors sit {middle:+.1f}s from the walk as a body "
                         f"— the set is wrong, not the walk")
        return None
    if len(apart) >= ANCHOR_AGREE_MIN:
        pts = [(line, at) for line, at, d in apart
               if abs(d - middle) <= ANCHOR_AGREE]
    else:
        pts = []
    if len(pts) < ANCHOR_AGREE_MIN:
        _anchored.why = (f"only {len(pts)} anchor(s) agreed with the walk "
                         f"— not enough to trust")
        return None

    first: dict = {}
    for n in range(len(flat)):
        first.setdefault(where[keep[n]][0], n)
    frames = emission.shape[0]
    bounds = [(0, 0)]
    for line, at in pts:
        n = first.get(line)
        f = int(round(at / per_frame))
        if n is None or n <= bounds[-1][0] or f <= bounds[-1][1] or f >= frames:
            continue
        bounds.append((n, f))
    if len(bounds) < 2:
        _anchored.why = "no anchor point was monotonic with the walk"
        return None
    lit = [sp for sp in spans if sp]
    total = sum(len(x) for x in flat) or 1
    pace = ((max(sp[-1].end for sp in lit) - min(sp[0].start for sp in lit))
            / total) if lit else 1.0

    def room(a: int, b: int) -> float:
        """Frames the words from `a` to `b` need before an anchor is doubted."""
        n = sum(len(x) for x in flat[a:b])
        return max(n, n * pace * ANCHOR_SQUEEZE)

    ok = [bounds[0]]
    for b in bounds[1:]:
        if b[1] - ok[-1][1] >= room(ok[-1][0], b[0]):
            ok.append(b)
    while len(ok) > 1 and frames - ok[-1][1] < room(ok[-1][0], len(flat)):
        ok.pop()
    ok.append((len(flat), frames))
    if len(ok) < 3:
        _anchored.why = "no anchor left its segment room for its own characters"
        return None

    out: list = []
    for (n0, f0), (n1, f1) in zip(ok, ok[1:]):
        got = aligner(emission[f0:f1], tokenizer(flat[n0:n1]))
        for span in got:
            out.append([_Span(s.start + f0, s.end + f0, s.score) for s in span]
                       if span else span)
    if len(out) != len(flat):
        _anchored.why = "the segmented walk came back the wrong length"
        return None
    _say(log, f"  anchored on {len(ok) - 2} line(s), in {len(ok) - 1} segments")
    _anchored.last = (len(ok) - 2, len(ok) - 1)
    at_line = {n: line for line, n in first.items()}
    _anchored.points = [(at_line.get(n), round(f * per_frame, 2))
                        for n, f in ok[1:-1]]
    return out


def _sounds_like(path: str, words: list[str], decoys: list[list[str]]):
    """How much better this audio matches `words` than songs it is not.

    None if it could not be judged -- the model would not run, or the decoys
    share no vocabulary with the transcript at all, which means a different
    language rather than a different recording.

    The whole file, not a clip -- tried a 45s and then a 90s window to cut
    the cost, and both measurably weakened the signal on real audio (a
    genuine match fell from a 0.35 margin to 0.13, under the 0.15 floor that
    is supposed to accept it). Whisper-base's error rate on fast or slangy
    vocals is high enough that a short window doesn't average it out, so a
    clip trades a real chance of throwing out the right recording for a
    speed-up that isn't worth that.
    """
    try:
        wave, rate = _read(path)
        dev, chunk, _why = room("gpu", ASR_COST, ASR_WINDOW, SPARE)
        if dev != "cpu":
            _cap(SPARE)
        heard.why = ""
        said = heard(wave, rate, dev, None, None, model=VERIFY_MODEL,
                     chunk=chunk)
        if not said:
            return None
        theirs = {_flat(w["word"]) for w in said if w.get("word")}
        theirs.discard("")

        def met(text):
            want = {_flat(w) for w in text} - COMMON
            want.discard("")
            return len(theirs & want) / max(1, len(want))

        null = statistics.median([met(d) for d in decoys])
        if null < NULL_FLOOR:
            return None
        return met(words) - null
    except Exception:
        return None


def _onsets(wave, rate: int) -> list[float]:
    """Times where the vocal stem starts making a new sound, in seconds.

    Spectral flux: the summed positive change in each mel band from one frame
    to the next, peaked. A sung word begins with energy appearing across many
    bands at once, which is visible in a spectrogram whether or not the model
    recognises the phoneme -- and where the phonemes are hard (fast rap, heavy
    production, screamed vowels) that visibility is exactly what CTC lacks.
    """
    import torch
    import torchaudio
    mel = torchaudio.transforms.MelSpectrogram(
        sample_rate=rate, n_fft=1024, hop_length=ONSET_HOP,
        n_mels=64)(wave[:1])
    power = torch.log1p(mel[0])
    flux = (power[:, 1:] - power[:, :-1]).clamp(min=0).sum(dim=0)
    if flux.numel() < 3:
        return []
    pad = ONSET_NEAR
    local = torch.nn.functional.avg_pool1d(
        flux[None, None], kernel_size=2 * pad + 1, stride=1, padding=pad)[0, 0]
    strong = flux > local * ONSET_OVER
    peak = (flux[1:-1] > flux[:-2]) & (flux[1:-1] >= flux[2:]) & strong[1:-1]
    step = ONSET_HOP / rate
    _onsets.flux, _onsets.step = flux.tolist(), step
    rise = flux.tolist()
    out = []
    for i in torch.nonzero(peak).flatten().tolist():
        k = i + 1
        for _ in range(ONSET_BACK):
            if k <= 0 or rise[k - 1] >= rise[k]:
                break
            k -= 1
        out.append(k * step)
    return out


def _snap(got: dict, marks: list[float], window: float) -> int:
    """Move each word's start back to the onset that begins it.

    Starts only. A word's end is where the next one begins far more often than
    it is a sound of its own, and moving both makes two errors out of one.
    Monotonic: a start may never pass the previous word's start.

    Asymmetric on purpose. A peak IS where the word starts, not a marker near
    it, and this aligner runs late -- every song measured sits at +0.08 to
    +0.12s. So the peak that belongs to a word is nearly always the one just
    BEFORE where the model put it, and the next peak forward is the following
    syllable. Searching symmetrically finds that next syllable about as often
    as it finds the right one, which turns a small error into a whole word.

    Two different things, kept apart. Which peaks are ELIGIBLE is judged from
    the model's guess, so a word with no onset near it is left exactly where
    the model put it -- that is what protects a fast syllabic run, where the
    peaks belong to syllables nobody wrote down. Which eligible peak WINS is
    judged from `start - ONSET_LATE`, where the sound that made the model fire
    is expected to be. Judging both from the guess is what kept the lateness in
    the answer even after snapping.
    """
    if not marks:
        return 0
    rows = sorted((r for r in got.get("words") or []
                   if isinstance(r.get("start"), (int, float))),
                  key=lambda r: r["start"])
    _snap.before = [[str(r.get("word") or ""),
                     float(r["start"]), float(r.get("end") or r["start"]),
                     float(r["score"]) if isinstance(r.get("score"),
                                                     (int, float)) else None]
                    for r in rows]
    back, fwd = window, window * ONSET_FORWARD
    moved, found, floor, at, prev = 0, 0, -1.0, 0, None
    for row in rows:
        while at < len(marks) - 1 and marks[at] < row["start"] - back:
            at += 1
        aim = row["start"] - ONSET_LATE
        best, gap = None, None
        for k in range(at, len(marks)):
            if marks[k] > row["start"] + fwd:
                break
            if marks[k] <= floor or marks[k] >= row["end"]:
                continue
            d = aim - marks[k]
            d = -d * ONSET_DOUBT if d < 0 else d
            if gap is None or d < gap:
                best, gap = marks[k], d
        if best is not None:
            found += 1
            if best != row["start"]:
                row["start"] = round(best, 3)
                moved += 1
        elif ONSET_LEAD_KEPT:
            row["start"] = round(max(floor, row["start"] - ONSET_LATE), 3)
        if prev is not None and prev["end"] > row["start"]:
            prev["end"] = row["start"]
        prev = row
        floor = row["start"]
    _snap.found, _snap.total = found, len(rows)
    return moved


def timings(wave, rate: int, words: list[str], device: str, window: float,
            offset: float = 0.0, log=None, stop=None, where=None,
            anchor=None, acoustic: str = "mms", per_line: bool = False,
            heard_at: dict | None = None) -> dict:
    """Where each of `words` is sung in `wave`, in the shape to_document wants.

    {"words": [{"i", "word", "start", "end", "score"}], "duration": seconds}.
    `i` indexes the caller's own list, so a word the aligner cannot take -- a
    bracketed [Chorus], an emoji, a fully non-Latin token -- is simply absent
    rather than shifting everything after it.
    """
    import torch
    w2v = acoustic == "w2v"
    if w2v:
        try:
            bundle, model, tokenizer, aligner = _w2v()
        except Exception as exc:
            _say(log, f"  wav2vec2 is not available here "
                      f"({type(exc).__name__}) — reading with MMS_FA instead")
            w2v = False
    if not w2v:
        bundle, model, tokenizer, aligner = _mms()
    wave = _resample(_channels(wave, 1), rate, bundle.sample_rate)

    aside = {n for n, w in enumerate(where or ()) if len(w) > 3
             and w[3] is not None}
    keep, flat = [], []
    for i, w in enumerate(words):
        f = _flat(w)
        if f and i not in aside:
            keep.append(i)
            flat.append(f)
    if not flat:
        raise RuntimeError("nothing in that text the aligner can read")

    def work(dev, win):
        _say(log, f"  {'wav2vec2-base-960h' if w2v else 'MMS_FA'} on {dev}, {win:.0f}s at a time")
        moved = model.to(dev)
        try:
            return _emission(_logits(moved) if w2v else moved, wave, dev, win,
                             log, stop=stop)
        finally:
            moved.to("cpu")
            if dev != "cpu":
                with contextlib.suppress(Exception):
                    torch.cuda.empty_cache()

    emission, per_frame = _shrinking(work, device, window, ALIGN_WINDOW,
                                     log, "MMS_FA")
    if emission.shape[0] < sum(len(f) for f in flat):
        raise RuntimeError(
            f"more text than audio: {sum(len(f) for f in flat)} characters to "
            f"place in {emission.shape[0]} frames. Wrong recording, or lyrics "
            f"for a longer version of it.")
    spans = aligner(emission, tokenizer(flat))
    if where is not None and anchor is not None:
        spans = _anchored(spans, aligner, tokenizer, emission, flat, keep,
                          where, per_frame, anchor, log) or spans
    if where is not None and per_line:
        spans = _per_line(spans, aligner, tokenizer, emission, flat, keep,
                          where, per_frame, heard_at, log) or spans

    out = []
    for n, span in enumerate(spans):
        if not span:
            continue
        start = span[0].start * per_frame + offset
        end = span[-1].end * per_frame + offset
        score = sum(s.score * (s.end - s.start) for s in span) / max(
            1e-9, sum(s.end - s.start for s in span))
        row = {"i": keep[n], "word": words[keep[n]],
               "start": round(float(start), 3),
               "end": round(float(end), 3),
               "score": round(float(score), 4)}
        if len(span) == len(flat[n]):
            row["chars"] = [(round(float(s.start * per_frame + offset), 3),
                             round(float(s.end * per_frame + offset), 3))
                            for s in span]
        out.append(row)
    if aside:
        out.extend(_asides(words, where, aside, spans, keep, aligner, tokenizer,
                           emission, per_frame, offset, log))
        out.sort(key=lambda r: r["i"])
    return {"words": out, "total": len(words),
            "duration": round(wave.shape[1] / bundle.sample_rate, 3)}


def _spread_frames(flat, words, f0: int, f1: int, per_frame: float,
                   offset: float) -> list[dict]:
    """Words shared evenly across a stretch of frames, by how long each is.

    Scored at MIN_SCORE exactly: the lowest score that survives to_document's
    floor, because a word dropped there is a word that leaves the page
    altogether. The renderer draws a line from its syllables, so an ad-lib with
    no syllable is not an ad-lib without a highlight -- it is a "(Woah)" the
    listener can no longer see. Kept, and marked as the weakest thing kept.
    """
    out = []
    total = sum(max(1, len(f)) for _n, f in flat)
    at = float(f0)
    for n, f in flat:
        take = (f1 - f0) * max(1, len(f)) / total
        start = at * per_frame + offset
        end = min(start + MAX_WORD, (at + take) * per_frame + offset)
        out.append({"i": n, "word": words[n],
                    "start": round(start, 3),
                    "end": round(max(end, start + MIN_SYL), 3),
                    "score": MIN_SCORE})
        at += take
    return out


def _asides(words, where, aside: set[int], spans, keep, aligner, tokenizer,
            emission, per_frame: float, offset: float, log=None) -> list[dict]:
    """Time each line's ad-libs against the frames its lead occupies.

    Deliberately not one walk over the song. Ad-libs are sung ON TOP of the
    line they answer, so their frames are the lead's frames -- the same audio,
    read for a second voice -- and a walk that had to cover the whole song
    would have to put them in order between the leads instead, which is the
    arrangement this exists to stop.

    Each line's ad-libs get their own short walk over their own line's span,
    so a mis-timed one costs that line and cannot move any other.
    """
    span_of: dict[int, tuple[int, int]] = {}
    for n, span in enumerate(spans):
        if not span:
            continue
        line = where[keep[n]][0]
        lo, hi = span[0].start, span[-1].end
        got = span_of.get(line)
        span_of[line] = (min(lo, got[0]), max(hi, got[1])) if got else (lo, hi)

    by_line: dict[int, list[int]] = {}
    for n in sorted(aside):
        by_line.setdefault(where[n][0], []).append(n)

    out: list[dict] = []
    for line, idx in by_line.items():
        bounds = span_of.get(line)
        if not bounds:
            continue
        f0, f1 = bounds
        f1 = min(emission.shape[0], f1 + max(1, int(ADLIB_REACH / per_frame)))
        flat = [(n, _flat(words[n])) for n in idx]
        flat = [(n, f) for n, f in flat if f]
        if not flat:
            continue
        got = None
        if f1 - f0 >= sum(len(f) for _n, f in flat):
            try:
                got = aligner(emission[f0:f1], tokenizer([f for _n, f in flat]))
            except Exception:
                got = None
        if got is None:
            out.extend(_spread_frames(flat, words, f0, f1, per_frame, offset))
            continue
        for (n, f), span in zip(flat, got):
            if not span:
                continue
            score = sum(s.score * (s.end - s.start) for s in span) / max(
                1e-9, sum(s.end - s.start for s in span))
            row = {"i": n, "word": words[n],
                   "start": round(float((span[0].start + f0) * per_frame + offset), 3),
                   "end": round(float((span[-1].end + f0) * per_frame + offset), 3),
                   "score": round(float(score), 4)}
            if len(span) == len(f):
                row["chars"] = [
                    (round(float((s.start + f0) * per_frame + offset), 3),
                     round(float((s.end + f0) * per_frame + offset), 3))
                    for s in span]
            out.append(row)
    if out:
        _say(log, f"  {len(out)} ad-lib word(s) timed under the lines they "
                  f"answer, in {len(by_line)} line(s)")
    return out


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
PHONE_MODEL = "facebook/wav2vec2-lv-60-espeak-cv-ft"

PHONE_COST = (1.6, 0.08)
PHONE_WINDOW = (8.0, 30.0)

IPA_VOWEL = frozenset("iɪyʏeøɛœæaɶɑɒɔoʊuʉɯɤʌɐəɚɜɝɞɵɘɨᵻᵿ" "ːˑ̩̈")
DIPHTHONG = frozenset({"aɪ", "aʊ", "eɪ", "oʊ", "ɔɪ", "əʊ", "ɪə", "eə", "ʊə",
                       "ɛə", "ɔə", "ɑɪ", "ɑʊ"})
ONSET = frozenset("""bl br ch cl cr dr dw fl fr gl gn gr kl kn kr ph pl pr ps
pn qu rh sc sh sk sl sm sn sp st sw th tr tw wh wr chr phr sch scl scr shr spl
spr squ str thr""".split())
VOWEL_LETTER = frozenset("aeiouy")
DIGRAPH = frozenset({"th", "sh", "ch", "ph", "wh", "gh", "ng", "qu", "zh"})
CHECKED = frozenset({"ɪ", "ɛ", "æ", "ʌ", "ʊ", "ɒ", "ᵻ", "ᵿ", "e"})

ENGLISH = frozenset("""a all am an and are as at be been but by can can't come
did do don't down for from get go going got had has have he her here him his
how i i'll i'm if in is it it's just know let like little love make me my never
no not now of oh on one only or our out over said say see she should so some
take tell than that the their them then there they this time to too up us very
was we well were what when where which who why will with would you your
you're yeah""".split())
ENGLISH_SHARE = 0.12
ENGLISH_MIN = 25

_g2p = None
SPOKEN_MAX = 20000
_spoken: dict[str, list[str]] = {}
_phone_built: tuple | None = None


def _english(words: list[str]) -> bool:
    """Is this document in English, surely enough to pronounce it as English?"""
    if sum(1 for w in words if UNSPACED.search(w)) > 0.02 * max(1, len(words)):
        return False
    seen = [f for f in (_flat(w) for w in words) if f]
    if len(seen) < ENGLISH_MIN:
        return False
    return sum(1 for w in seen if w in ENGLISH) >= ENGLISH_SHARE * len(seen)


def _speaker(lang: str = "en-us"):
    """phonemizer's espeak backend for `lang`, or False if there is none.

    Optional in the same way pykakasi and uroman are optional: a machine
    without it keeps the behaviour it had, which is whole words.

    Cached per language rather than once, because asking for a second one is
    now possible -- see divide()'s `lang`. espeak itself speaks a hundred of
    them; what is English here is not the phonemes but what is done with them
    afterwards, and that is documented where it is decided rather than here.
    """
    global _g2p
    if _g2p is False:
        return False
    if not isinstance(_g2p, dict):
        _g2p = {}
    if lang not in _g2p:
        _g2p[lang] = False
        try:
            from phonemizer.backend import EspeakBackend
        except Exception:
            return _g2p[lang]
        head = (lang or "").split("-")[0]
        for name in (lang, f"{head}-{head}", head):
            if not name:
                continue
            try:
                try:
                    _g2p[lang] = EspeakBackend(
                        name, with_stress=False,
                        language_switch="remove-flags",
                        words_mismatch="ignore")
                except TypeError:
                    _g2p[lang] = EspeakBackend(name, with_stress=False)
                break
            except Exception:
                continue
    return _g2p[lang]


def _pronounce(words: list[str], lang: str = "en-us") -> None:
    """Fill `_spoken` for every word in the list that is not in it yet.

    Asked for the whole song in one call. phonemizer pays its cost per call
    rather than per word -- it is talking to a library through a lock and a
    text protocol -- and a call per word took longer than the alignment it was
    decorating.
    """
    back = _speaker(lang)
    if not back:
        return
    want = sorted({w for w in words if w and (lang, w) not in _spoken})
    if not want:
        return
    if len(_spoken) + len(want) > SPOKEN_MAX:
        _spoken.clear()
        want = sorted({w for w in words if w})
    try:
        from phonemizer.separator import Separator
        got = back.phonemize(want, separator=Separator(phone=" ", word="|"),
                             strip=True, njobs=1)
    except Exception:
        for w in want:
            _spoken[(lang, w)] = []
        return
    for w, said in zip(want, got):
        _spoken[(lang, w)] = [p for p in str(said).replace("|", " ").split() if p]


def _vowelly(phone: str) -> bool:
    return any(c in IPA_VOWEL for c in phone)


def _nuclei(phones: list[str]) -> list[int]:
    """Which phones are syllable nuclei."""
    out: list[int] = []
    for i, p in enumerate(phones):
        if not _vowelly(p):
            continue
        if out and i == out[-1] + 1:
            pair = (phones[out[-1]] + p).replace("ː", "").replace("ˑ", "")
            if pair in DIPHTHONG:
                continue
        out.append(i)
    return out


def _checked(phone: str) -> bool:
    return phone.replace("ː", "").replace("ˑ", "") in CHECKED


def _open(phones: list[str], syl: list[tuple[int, int]]) -> list[bool]:
    """Whether each syllable is allowed to end without a consonant."""
    out = []
    for lo, hi in syl:
        nuc = next((p for p in phones[lo:hi + 1] if _vowelly(p)), "")
        out.append(not _checked(nuc))
    return out


def _phone_syllables(phones: list[str]) -> list[tuple[int, int]]:
    """One phone-index range per syllable, dividing by maximal onset.

    A consonant between two vowels goes forward onto the syllable it precedes
    rather than staying with the one it follows -- that is what makes "around"
    a-round instead of ar-ound, and it is also how it is sung, the consonant
    landing at the top of the next note rather than the bottom of the last.
    A run of them keeps its first consonant behind as a coda and hands over at
    most two, which is about as much as an English syllable starts with:
    "instant" divides in-stant, "extra" ex-tra.

    Except after a checked vowel, which has to keep a consonant of its own --
    see CHECKED. That is what separates "a-round" from "dis-tant", and it is
    the same reduction the spelling gets below, so the letters on screen and
    the sounds being timed divide in the same place.
    """
    nuc = _nuclei(phones)
    if len(nuc) < 2:
        return [(0, len(phones) - 1)] if phones else []
    starts = [0]
    for a, b in zip(nuc, nuc[1:]):
        gap = b - a - 1
        take = 1 if gap == 1 else min(max(gap - 1, 0), 2)
        if _checked(phones[a]):
            take = min(take, gap - 1)
        starts.append(b - max(take, 0))
    return [(s, (starts[k + 1] - 1) if k + 1 < len(starts) else len(phones) - 1)
            for k, s in enumerate(starts)]


def _letters(word: str) -> tuple[str, list[int]]:
    """A word as the aligner spells it, and where each letter came from.

    _flat's answer with an index alongside it, so a cut made in the flattened
    spelling can be made in the ORIGINAL -- which is what goes on screen, with
    its capitals and its comma still attached. Done a character at a time so
    the two lists cannot drift apart.
    """
    flat, idx = [], []
    for i, ch in enumerate(word):
        s = unicodedata.normalize("NFKD", ch)
        s = "".join(c for c in s if not unicodedata.combining(c))
        s = KEEP.sub("", s.lower().replace("’", "'").replace("‘", "'"))
        for c in s:
            flat.append(c)
            idx.append(i)
    return "".join(flat), idx


def _vowel_runs(flat: str) -> list[tuple[int, int]]:
    """Runs of vowel letters -- the places a syllable could be centred."""
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(flat):
        if flat[i] in VOWEL_LETTER and not (flat[i] == "y" and i == 0):
            j = i
            while j + 1 < len(flat) and flat[j + 1] in VOWEL_LETTER:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
_hyphen: dict = {}


def _speller(lang: str):
    """pyphen for `lang`, or None. Cached per language, built on first ask."""
    if lang in _hyphen:
        return _hyphen[lang]
    got = None
    try:
        import pyphen
        want = (lang or "en-us").replace("-", "_")
        names = {n.lower(): n for n in pyphen.LANGUAGES}
        pick = names.get(want.lower())
        if pick is None:
            head = want.split("_")[0].lower()
            pick = names.get(head) or next(
                (n for k, n in sorted(names.items()) if k.split("_")[0] == head),
                None)
        if pick:
            got = pyphen.Pyphen(lang=pick)
    except Exception:
        got = None
    _hyphen[lang] = got
    return got


def _dict_cuts(flat: str, want: int, lang: str) -> list[int] | None:
    """Where `flat` divides according to pyphen, or None.

    None when there is no dictionary, or when the dictionary disagrees with the
    pronunciation about how many pieces there are -- see the note above.
    """
    speller = _speller(lang)
    if speller is None or want < 2:
        return None
    try:
        marked = speller.inserted(flat, hyphen="\x00")
    except Exception:
        return None
    parts = [p for p in marked.split("\x00") if p]
    if len(parts) != want or "".join(parts) != flat:
        return None
    cuts, at = [0], 0
    for p in parts[:-1]:
        at += len(p)
        cuts.append(at)
    return cuts


def _cut_letters(flat: str, want: int, opened: list[bool] | None = None) -> list[int]:
    """Where to divide a spelling into `want` pieces. The start of each.

    The pronunciation has already said how many pieces there are; the letters
    only have to say where. Vowel runs are the candidates, surplus ones are
    merged away -- which is what a silent e is, seen from here, and why "hope"
    comes back whole -- and the consonants between two survivors move forward
    onto the next piece as far as an English word is allowed to begin.

    Where this is known to be wrong: a compound with a silent e inside it.
    "someone" divides som-eone, because the e of "some" and the o of "one"
    are adjacent letters and are read as one vowel run before anything knows
    there is a seam between two words there. The count is right and the times
    are right -- it is one letter in the wrong piece -- and every fix for it
    tried here cost more elsewhere: merging the other way round to catch
    "someone" turns "believe" into belie-ve.
    """
    runs = _vowel_runs(flat)
    if want < 2 or len(runs) < 2:
        return [0]
    while len(runs) > want:
        gaps = [(runs[k + 1][0] - runs[k][1] - 1, k) for k in range(len(runs) - 1)]
        _, k = min(gaps, key=lambda g: (g[0], -g[1]))
        runs = runs[:k] + [(runs[k][0], runs[k + 1][1])] + runs[k + 2:]
    cuts = [0]
    for k in range(1, len(runs)):
        lo, hi = runs[k - 1][1] + 1, runs[k][0]
        cluster = flat[lo:hi]
        pair = next((i for i in range(len(cluster) - 1)
                     if cluster[i] == cluster[i + 1] or cluster[i:i + 2] == "ck"),
                    None)
        if pair is not None:
            cuts.append(lo + pair + (2 if cluster[pair:pair + 2] == "ck" else 1))
            continue
        take = 0
        for n in range(min(len(cluster), 3), 0, -1):
            if n == 1 or cluster[-n:] in ONSET:
                take = n
                break
        closed = any(c not in VOWEL_LETTER
                     for c in flat[runs[k - 1][0]:runs[k - 1][1] + 1])
        if opened is not None and not opened[k - 1] and take and not closed:
            short = min(take, len(cluster) - 1)
            at = len(cluster) - short
            if short and cluster[at - 1:at + 1] in DIGRAPH:
                short = 0
            take = short
        cuts.append(hi - take)
    return cuts if all(b > a for a, b in zip(cuts, cuts[1:])) else [0]


def _pieces(word: str, row: dict, phones: list[str],
            spans: list[tuple[float, float]] | None,
            lang: str = "en-us") -> list | None:
    """[(text, start, end)] dividing one word, or None to leave it whole.

    `spans` is tier 3: one measured (start, end) per phone. Without it the
    boundary times come from the character spans MMS_FA already returned,
    which is tier 2 -- the cut is in the right place either way, and what the
    phoneme model adds is where that place is in the audio.
    """
    syl = _phone_syllables(phones)
    if len(syl) < 2:
        return None
    flat, idx = _letters(word)
    if not flat or flat != _flat(word):
        return None
    cuts = (_dict_cuts(flat, len(syl), lang)
            or _cut_letters(flat, len(syl), _open(phones, syl)))
    if len(cuts) < 2:
        return None
    start, end = float(row["start"]), float(row["end"])
    if end - start < MIN_SYL * len(syl):
        return None
    chars = row.get("chars")
    at: list[float] = []
    if spans and len(cuts) == len(syl):
        at = [float(spans[syl[k][0]][0]) for k in range(1, len(syl))]
    elif chars and len(chars) == len(flat):
        at = [float(chars[c][0]) for c in cuts[1:]]
    if len(at) != len(cuts) - 1:
        return None
    got, prev = [], start
    for k, t in enumerate(at):
        ceiling = end - MIN_SYL * (len(at) - k)
        prev = min(max(float(t), prev + MIN_SYL), max(ceiling, prev + MIN_SYL))
        got.append(prev)
    bounds = [start] + got + [end]
    out = []
    for k in range(len(cuts)):
        a = idx[cuts[k]] if k else 0
        b = idx[cuts[k + 1]] if k + 1 < len(cuts) else len(word)
        text = word[a:b]
        if not text:
            return None
        out.append((text, round(bounds[k], 3), round(bounds[k + 1], 3)))
    if "".join(t for t, _a, _b in out) != word:
        return None
    return out


def _phone_ctc():
    """The phoneme model and its processor, built once, or False.

    Built on the CPU and moved per call, the same bargain _mms() makes: about
    1.2 GB the first time from Hugging Face's host, and the weights are a
    gigabyte in the way of anything else on the card between calls.
    """
    global _phone_built
    if _phone_built is None:
        try:
            from transformers import AutoModelForCTC, AutoProcessor
            proc = AutoProcessor.from_pretrained(PHONE_MODEL)
            mod = AutoModelForCTC.from_pretrained(PHONE_MODEL)
            mod.eval()
            _phone_built = (proc, mod)
        except Exception:
            _phone_built = False
    return _phone_built


def _ids(vocab: dict, phones: list[str]) -> list[int]:
    """espeak's phones as the model's own symbols.

    Longest match against the vocabulary rather than a table written out
    here. The two agree about most of it -- the model was trained on espeak's
    output -- and where they do not, this is the only way to find out which
    spelling of a sound the model actually knows: espeak writes "ɑː" where the
    vocabulary may have "ɑ" and a separate "ː", or neither.
    """
    out: list[int] = []
    for phone in phones:
        i = 0
        while i < len(phone):
            for n in range(min(5, len(phone) - i), 0, -1):
                got = vocab.get(phone[i:i + n])
                if got is not None:
                    out.append(int(got))
                    i += n
                    break
            else:
                i += 1
    return out


def _phone_spans(wave, rate: int, rows: list[dict], said: list[list[str]],
                 device: str, window: float, offset: float, log=None,
                 stop=None) -> dict:
    """{row index: [(start, end) per phone]}, measured against PHONE_MODEL.

    One monotonic pass over the whole song, the same shape as the character
    alignment above and for the same reason: cutting the text up needs to
    know where the cuts go, which is the question being asked.
    """
    import torch
    import torchaudio
    _phone_spans.gap, _phone_spans.apart = [], []
    proc, mod = _phone_ctc()
    vocab = proc.tokenizer.get_vocab()
    blank = proc.tokenizer.pad_token_id
    blank = 0 if blank is None else int(blank)

    tokens, span_of = [], []
    for n, phones in enumerate(said):
        got = _ids(vocab, phones) if phones else []
        if got:
            span_of.append((n, len(tokens), len(got)))
            tokens += got
    if not tokens:
        return {}

    wave = _resample(_channels(wave, 1), rate, RATE)

    def work(dev, win):
        _say(log, f"  {PHONE_MODEL.split('/')[-1]} on {dev}, {win:.0f}s at a time")
        moved = mod.to(dev)
        try:
            return _emission(_logits(moved), wave, dev, win, log, "phonemes",
                             stop=stop)
        finally:
            moved.to("cpu")
            if dev != "cpu":
                with contextlib.suppress(Exception):
                    torch.cuda.empty_cache()

    emission, per_frame = _shrinking(work, device, window, PHONE_WINDOW,
                                     log, "phonemes")
    if emission.shape[0] < len(tokens):
        raise RuntimeError(f"{len(tokens)} phonemes to place in "
                           f"{emission.shape[0]} frames")
    got, scores = torchaudio.functional.forced_align(
        emission[None], torch.tensor([tokens], dtype=torch.int32), blank=blank)
    spans = torchaudio.functional.merge_tokens(got[0], scores[0], blank=blank)
    if len(spans) != len(tokens):
        raise RuntimeError(f"{len(spans)} spans for {len(tokens)} phonemes")

    out: dict[int, list] = {}
    for n, at, count in span_of:
        per, k = [], at
        for phone in said[n]:
            width = len(_ids(vocab, [phone]))
            if not width:
                per.append(None)
                continue
            per.append((spans[k].start * per_frame + offset,
                        spans[k + width - 1].end * per_frame + offset))
            k += width
        for i, item in enumerate(per):
            if item is None:
                near = next((p for p in per[i + 1:] if p), None) or \
                       next((p for p in reversed(per[:i]) if p), None)
                per[i] = near or (0.0, 0.0)
        row = rows[n]
        lo, hi = per[0][0], per[-1][1]
        share = min(hi, row["end"]) - max(lo, row["start"])
        if share <= 0.5 * min(hi - lo, row["end"] - row["start"]):
            _phone_spans.apart.append(
                [str(row.get("word") or ""), round(row["start"], 3),
                 round(lo, 3)])
            continue
        _phone_spans.gap.append(
            [str(row.get("word") or ""), round(row["start"], 3), round(lo, 3)])
        out[n] = per
    return out


def _logits(mod):
    """`mod` as the callable _emission expects: a chunk in, log probs out.

    Two differences from a torchaudio model, both of them the feature
    extractor's job in the library this came from. It answers with an object
    rather than a tuple, and it was trained on input normalised to zero mean
    and unit variance -- done per window here, which is the same arithmetic
    the extractor would do per utterance.
    """
    import torch

    def run(chunk):
        x = chunk - chunk.mean()
        x = x / (x.std() + 1e-7)
        out = mod(x)
        got = out[0] if isinstance(out, tuple) else getattr(out, "logits", None)
        if got is None:
            got = out[0]
        return torch.log_softmax(got.float(), dim=-1), None
    return run


def divide(wave, rate: int, words: list[str], result: dict, want: str = "auto",
           spare: float = SPARE, offset: float = 0.0, log=None,
           stop=None, lang: str = "") -> int:
    """Cut words into syllables, in place on `result`. How many.

    English unless `lang` names an espeak voice -- see the note at the gate
    below for why that is a switch rather than a detector.

    Never raises and never removes anything: a word this cannot divide keeps
    the timing it already had, which is the timing that was measured.
    """
    rows = [r for r in (result or {}).get("words") or [] if r.get("word")]
    if not rows:
        return 0
    if lang:
        _say(log, f"  dividing as {lang} — the split follows English spelling "
                  f"rules, so check the result")
    elif _english(words):
        lang = "en-us"
    else:
        _say(log, "  not English — leaving the words whole")
        return 0
    if not _speaker(lang):
        _say(log, f"  no phonemizer for {lang} — leaving the words whole")
        return 0
    flats = [_flat(r["word"]) for r in rows]
    _pronounce(flats, lang)
    said = [_spoken.get((lang, f)) or [] for f in flats]
    if not any(said):
        _say(log, "  espeak said nothing — leaving the words whole")
        return 0

    spans = {}
    if _phone_ctc():
        dev, win, why = room(want, PHONE_COST, PHONE_WINDOW, spare)
        _say(log, f"  {why}")
        if dev != "cpu":
            _cap(spare)
        try:
            spans = _phone_spans(wave, rate, rows, said, dev, win, offset,
                                 log, stop)
        except Stopped:
            raise
        except Exception as exc:
            _say(log, f"  phoneme timing unavailable ({type(exc).__name__}) — "
                      f"cutting on the characters instead")
            spans = {}
    else:
        _say(log, "  no phoneme model — cutting on the characters instead")

    cut = 0
    for n, row in enumerate(rows):
        if not said[n]:
            continue
        try:
            got = _pieces(row["word"], row, said[n], spans.get(n), lang)
        except Exception:
            got = None
        if got:
            row["parts"] = got
            cut += 1
    return cut


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
heard.why = ""
_anchored.last = None
_anchored.why = ""
_anchored.points = []


def align(audio_path: str, doc, offset: float = 0.0, *, stems: bool = True,
          want: str = "auto", spare: float = SPARE, name: str = MODEL,
          keep: str | None = None, syllables: bool = True, anchors: bool = False,
          asr: str | None = None, asr_cpu: bool = False, debug: bool = False,
          target: float | None = None, syl_lang: str = "",
          anchors_from: list[dict] | None = None, acoustic: str = "auto",
          per_line: bool = False, verify: bool = True,
          onsets: bool = True, emit_from: str = "stem",
          decoys: list[list[str]] | None = None,
          log=None, stop=None) -> dict | None:
    """Time one song against one file, and bring back a timed document.

    Returns None on anything at all going wrong, with the reason on
    `align.last_error` and, where there was one, the last few frames of the
    traceback on `align.last_trace`. The caller keeps whatever it already had.

    The traceback is worth keeping rather than raising. Everything in here fails
    for reasons that are somebody else's -- a model download that half-arrived,
    a demucs built against another torch, a driver that has gone away -- and
    "RuntimeError" on its own sends you looking in the wrong file.
    """
    global _LOUD
    align.last_error, align.last_trace, align.stopped = "", [], False
    _snap.found = _snap.total = None
    _LOUD = bool(debug)
    log = _tracing(log, debug)
    if debug:
        _say(log, f"debug on — {ASR_MODEL if asr is None else asr} for anchors, "
                  f"{name} for the stem, {PHONE_MODEL.split('/')[-1]} for "
                  f"syllables")
        _say(log, f"  every stage says where it runs and what it holds. "
                  f"'vram' is this process's own reserve, not the card's free "
                  f"figure; 'ram' is resident memory.")
    if not audio_path or not os.path.exists(audio_path):
        align.last_error = f"no such audio file: {audio_path}"
        return None
    if _torch() is None:
        align.last_error = ("torch is not installed.\n"
                            "        pip install --user torch torchaudio")
        return None
    heard.why = ""
    _anchored.last = None
    _anchored.why = ""
    _anchored.points = []
    align.overlap = None
    words, where = words_of(doc)
    if not words:
        align.last_error = "no words in that document to align"
        return None
    try:
        import torchaudio                                    # noqa: F401
    except ImportError:
        align.last_error = ("torchaudio is not installed.\n"
                            "        pip install --user torchaudio")
        return None

    def step(make) -> None:
        if debug:
            _say(log, make() if callable(make) else make)

    try:
        _stop(stop)
        step("stage 1/5  reading the audio")
        wave, rate = _read(audio_path)
        step(lambda: f"  {wave.shape[0]}ch x {wave.shape[1]} samples at "
                     f"{rate} Hz ({wave.shape[1] / rate:.0f}s)")
        if target and target > 0:
            extra = wave.shape[1] / float(rate) - float(target)
            if extra > LEAD_MIN:
                lead = lead_in(wave, rate)
                shift = min(lead, extra)
                if shift > LEAD_MIN:
                    offset -= shift
                    _say(log, f"  this copy is {extra:.1f}s longer than the "
                              f"track and opens with {lead:.1f}s of silence — "
                              f"taking {shift:.1f}s off every time")
                else:
                    step(lambda: f"  {extra:.1f}s longer than the track, but "
                                 f"only {lead:.1f}s of it is at the front — "
                                 f"no correction")
        step("stage 2/5  separating the vocal")
        mix, mix_rate = (wave.clone(), rate) if emit_from == "mix" else (None, 0)
        if stems:
            dev, win, why = room(want, DEMUCS_COST, DEMUCS_WINDOW, spare)
            _say(log, f"  {why}")
            if dev != "cpu":
                _cap(spare)
            wave, rate = separate(wave, rate, dev, win, name, log, stop)
            voice = Speech.of(wave, rate)
            if voice is not None:
                _say(log, f"  silero found {len(voice.spans)} sung phrases in "
                          f"the stem")
            else:
                voice = Voice.of(wave, rate)
                _say(log, "  listening to the stem for where words end"
                          if voice is not None else
                          "  no energy envelope — words run on by the flat hold")
            if keep:
                _write(keep, wave, rate)
                _say(log, f"  vocal stem kept at {keep}")
        else:
            _say(log, "  vocal separation off — aligning against the full mix")
            voice = None
        step("stage 3/5  hearing where the lines fall")
        dev, win, why = room(want, ALIGN_COST, ALIGN_WINDOW, spare)
        _say(log, f"  {why}")
        if dev != "cpu":
            _cap(spare)
        _stop(stop)
        pin, spoken, heard_lines = None, None, None
        if anchors:
            adev, achunk, awhy = room(want, ASR_COST, ASR_WINDOW, spare)
            _say(log, f"  {awhy}")
            if adev != "cpu":
                _cap(spare)
            said = list(anchors_from) if anchors_from else heard(
                wave, rate, adev, log, stop, model=asr, on_cpu=asr_cpu,
                chunk=achunk)
            _stop(stop)
            if said:
                _first, spoken = _model_lines(doc, said)
                heard_lines = _first
                step(lambda: f"  heard {len(said)} words; "
                             f"{len(_first)} lines placed"
                             + (f", {min(_first.values()):.1f}s to "
                                f"{max(_first.values()):.1f}s" if _first else ""))

                def pin(_mine, _doc=doc, _said=said):
                    return _model_points(_doc, _said, log)
        elif verify:
            adev, achunk, awhy = room(want, ASR_COST, ASR_WINDOW, spare)
            if adev != "cpu":
                _cap(spare)
            release()
            heard.why = ""
            said = heard(wave, rate, adev, log, stop, model=asr or VERIFY_MODEL,
                         on_cpu=asr_cpu, chunk=achunk)
            if not said and heard.why:
                _say(log, f"  could not listen ({heard.why}) — this says "
                          f"nothing about the recording")
            if said:
              try:
                theirs = {_flat(w["word"]) for w in said if w.get("word")}
                theirs.discard("")

                def met(text):
                    want = {_flat(w) for w in text} - COMMON
                    want.discard("")
                    return len(theirs & want) / max(1, len(want))

                share = met(words)
                align.overlap = round(share, 3)
                if decoys:
                    null = statistics.median([met(d) for d in decoys])
                    if null < NULL_FLOOR:
                        _say(log, f"  the speech model heard {len(said)} words, "
                                  f"but songs this is not scored {null*100:.0f}%"
                                  f" — no common ground to measure against, so "
                                  f"this says nothing about the recording")
                        align.overlap = None
                        raise _NoVerdict
                    align.overlap = (round(share, 3), round(null, 3))
                    _say(log, f"  the speech model heard {len(said)} words: "
                              f"{share*100:.0f}% of this song's words against "
                              f"{null*100:.0f}% for songs it is not"
                              + ("" if share - null >= HEARD_MARGIN else
                                 " — THIS MAY NOT BE THE RIGHT RECORDING"))
                else:
                    _say(log, f"  the speech model heard {len(said)} words, "
                              f"{share*100:.0f}% of the lyric's vocabulary "
                              f"(no decoys given, so no floor to compare with)")
              except _NoVerdict:
                pass
        elif log:
            _say(log, "  anchoring off — one pass")
        step("stage 4/5  placing the words")
        pick = acoustic
        if pick == "auto":
            pick = "w2v" if _english(words) else "mms"
            step(lambda: f"  {pick} chosen: the words "
                         f"{'are' if pick == 'w2v' else 'are not'} English")
        if mix is not None:
            _say(log, "  reading the words off the untouched mix, not the stem")
        got = timings(mix if mix is not None else wave,
                      mix_rate if mix is not None else rate,
                      words, dev, win, offset, log, stop,
                      where=where, anchor=pin, acoustic=pick,
                      per_line=per_line, heard_at=heard_lines)
        step(lambda: f"  {len(got.get('words') or [])} of {len(words)} "
                     f"words have a span")
        if onsets:
            try:
                marks = _onsets(wave, rate)
                _onsets.offset = offset
                moved = _snap(got, [t + offset for t in marks], ONSET_WINDOW)
                _say(log, f"  {len(marks)} onsets in the spectrogram, "
                          f"{moved} word start(s) moved to one "
                          f"({_snap.found} of {_snap.total} words had a peak "
                          f"to move to)")
            except Exception as exc:
                _say(log, f"  onsets: {type(exc).__name__}: {exc}")
        step("stage 5/5  dividing them into syllables")
        if syllables:
            try:
                cut = divide(wave, rate, words, got, want, spare, offset,
                             log, stop, lang=syl_lang)
                if cut:
                    _say(log, f"  {cut} words divided into syllables")
            except Stopped:
                raise
            except Exception as exc:
                _say(log, f"  syllables: {type(exc).__name__}: {exc}")
    except Stopped:
        align.stopped = True
        align.last_error = "stopped"
        return None
    except Exception as exc:
        import traceback
        align.last_error = f"{type(exc).__name__}: {exc}"
        align.last_trace = traceback.format_exc().strip().splitlines()[-6:]
        return None
    torch = _torch()
    if torch is not None:
        with contextlib.suppress(Exception):
            torch.cuda.empty_cache()
    placed = len(got.get("words") or [])
    _say(log, f"  {placed} of {len(words)} words placed")
    out = to_document(doc, words, where, got, voice, spoken)
    if out is None:
        align.last_error = (
            f"{placed} of {len(words)} words came back, and none of them "
            f"passed the score floor ({MIN_SCORE}) and the {MAX_WORD:.0f}s "
            f"word limit. Most likely the wrong recording.")
    return out


align.last_error = ""
align.overlap = None
align.last_trace: list[str] = []
align.stopped = False


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
LENGTH_TOL = 3.0
LENGTH_TOL_MINE = 10.0
ALT_VERSION = re.compile(
    r"\b(live|acoustic|cover|remix|instrumental|karaoke|nightcore|demo|"
    r"tribute|rehearsal|session|mashup|parody|sped[\s-]?up|slowed)\b", re.I)


FETCH_TRIES = 5
PIN_TRIES = 3


SEARCHES = ("scsearch", "ytsearch")
PREVIEW = 30.0


def find(query: str, length: float, tries: int = 8,
         artist: str = "") -> list[tuple[str, float]]:
    """Every search hit whose length matches the track, best first.

    Metadata only -- nothing is downloaded until something has been chosen.

    A list rather than the single best, because the best one may not be
    downloadable and the next is usually the same recording: uploads that agree
    on the length to within a second or two have, in practice, agreed about
    which recording they are.

    Two places are searched. An upload from the artist's own account wins
    wherever it is -- that is the master, and nothing else here is better
    evidence of which recording this is -- and is judged against a looser
    length tolerance (LENGTH_TOL_MINE) than everyone else's uploads, because
    it is exactly the recording most likely to differ by a couple of seconds
    from the length Genius or Apple report for it: a different silence trim,
    a different encoder, no ID3 padding. The strict tolerance was written for
    telling apart a radio edit from an album cut, not for taking points off
    the one upload most likely to actually be right. Failing an artist match,
    SoundCloud comes first: what is wanted is the recording the streaming
    services carry, and on SoundCloud that is usually the one upload there
    is, where YouTube has the video edit, the topic-channel copy, the live
    take and the lyric video, all of them plausible and only one of them
    right.

    YouTube stays as the fallback, and a needed one: plenty of songs are not
    on SoundCloud at all, and plenty more are there only as the 30-second
    preview a label upload gives a listener who is not signed in. Those are
    dropped rather than reported as a near miss, since "the closest was 30s"
    describes the paywall and not the search.

    Titles are not matched on, only lengths -- with one exception. SoundCloud
    titles carry whatever the uploader felt like adding: a producer tag, a
    feature, the label. A title test built to catch those would throw away
    the very uploads worth having, so there isn't one. What IS read out of
    the title is a short, specific list of words that name a different
    recording rather than decorate the same one -- "live", "acoustic",
    "remix" -- and a hit that says one of those is ranked below every hit
    that doesn't, even one on the artist's own account: the widened tolerance
    above is there so a real master a few seconds off is not thrown out, not
    so a live take of the same length can stand in for it.

    What was rejected is left on `find.near` -- the closest hit that missed the
    tolerance -- so a caller can say "wanted 300s, the closest was 295s"
    instead of leaving the user to go and look for themselves.
    """
    find.near, find.seen = None, 0
    who = GR.key(_bare(artist)) if artist else ""
    seen_urls: set[str] = set()
    rows: list[tuple[str, str]] = []
    bare = query.split(" ", 1)[1] if " " in query else ""
    asks = []
    for where in SEARCHES:
        asks.append((where, query))
        if bare:
            asks.append((where, bare))
        if where == "ytsearch":
            asks.append((where, f"{query} audio"))

    def ask_for(job: tuple[str, str]) -> list[tuple[str, str]]:
        where, ask = job
        cmd = ["yt-dlp", f"{where}{tries}:{ask}", "--dump-json",
               "--no-warnings", "--skip-download", "--no-playlist",
               "--flat-playlist"]
        try:
            got = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=120)
        except Exception:
            return []
        return [(where, row) for row in got.stdout.splitlines()]

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(asks)) as pool:
        for got in pool.map(ask_for, asks):
            rows.extend(got)
    keep, near = [], None
    for where, row in rows:
        try:
            hit = json.loads(row)
        except json.JSONDecodeError:
            continue
        dur = float(hit.get("duration") or 0)
        url = hit.get("webpage_url")
        if not dur or not url:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        if (where == "scsearch" and abs(dur - PREVIEW) < 0.5
                and length > PREVIEW * 1.5):
            continue
        find.seen += 1
        gap = abs(dur - length) if length else 0.0
        theirs = GR.key(_bare(str(hit.get("uploader") or "")))
        mine = _same_artist(theirs, who)
        tol = LENGTH_TOL_MINE if mine else LENGTH_TOL
        if length and gap > tol:
            if near is None or gap < near[0]:
                near = (gap, dur, str(hit.get("title") or "")[:60])
            continue
        alt = bool(ALT_VERSION.search(str(hit.get("title") or "")))
        keep.append((gap, url, dur, mine, alt, where))

    def rank(k):
        gap, url, _dur, mine, alt, where = k
        return (1 if alt else 0, 0 if mine else 1,
                SEARCHES.index(where), round(gap, 1), gap, url)

    keep.sort(key=rank)
    if near:
        find.near = (near[1], near[2])
    find.mine = {url: mine for _gap, url, _dur, mine, _a, _s in keep}
    return [(url, dur) for _gap, url, dur, _m, _a, _s in keep]


find.near: tuple | None = None
find.seen = 0
find.mine: dict = {}


AUDIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "fetched"
AUDIO_CAP_GB = 8.0
YT_CLIENTS = ("tv_simply", "android_vr")
HARD = (
    ("Sign in to confirm", "YouTube wants a sign-in for this one (bot check "
                           "— set $MILD_COOKIES to a browser to pass one)"),
    ("not a bot", "YouTube wants a sign-in for this one (bot check "
                  "— set $MILD_COOKIES to a browser to pass one)"),
    ("DRM protected", "SoundCloud streams this one through Go+ only — "
                       "signed in or not, yt-dlp cannot decrypt it"),
    ("Go+ song", "SoundCloud streams this one through Go+ only — "
                 "signed in or not, yt-dlp cannot decrypt it"),
)
FETCH_RETRIES = 4
RETRY_WAIT = 2.0


def _kept(tid: str):
    """The copy kept for this track, touched so it counts as recently used."""
    got = AUDIO_DIR / f"{tid}.wav"
    if got.exists() and got.stat().st_size > 1024:
        with contextlib.suppress(Exception):
            os.utime(got)
        return got
    return None


def _keep(tid: str, path: str) -> None:
    """Keep this copy for next time, and stay under the cap."""
    with contextlib.suppress(Exception):
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, AUDIO_DIR / f"{tid}.wav")
        files = sorted(AUDIO_DIR.glob("*.wav"), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        while files and total > AUDIO_CAP_GB * 2**30:
            gone = files.pop(0)
            total -= gone.stat().st_size
            gone.unlink(missing_ok=True)


def _hard(said: str) -> str:
    """A refusal there is no point knocking twice on, in plain words."""
    return next((why for x, why in HARD if x in said), "")


LYRICS_DIR = pathlib.Path(__file__).resolve().parent.parent / "lyrics"
DECOY_MIN_WORDS = 20


def local_decoys(exclude: str = "", n: int = 6) -> list[list[str]]:
    """A few other songs' words, plain, to give `fetched`'s acoustic check
    something wrong to compare against.

    `_sounds_like` needs both sides of the question -- not just "does the
    audio contain these words" but "does it contain them any more than it
    contains some OTHER song's" -- and until now nothing outside a full
    dataset build ever handed it that half, so the check was written and then
    never actually run by anything a person clicks. What is sitting on disk
    already, in `lyrics/`, is every other song this project has a TTML for:
    plenty for a floor, and free, because nothing here is fetched or timed --
    only read.

    Picked at random rather than the six longest files or the six most
    recent, so the floor is not quietly the same six songs on every call.
    """
    try:
        files = [f for f in LYRICS_DIR.glob("*.ttml")
                 if GR.key(f.stem) != GR.key(exclude or "")]
    except OSError:
        return []
    import random
    random.shuffle(files)
    out: list[list[str]] = []
    for f in files:
        if len(out) >= n:
            break
        try:
            body = LS.parse_ttml(f.read_text(errors="replace"))
        except Exception:
            continue
        if not body:
            continue
        words = [_flat(w) for item in LS._items(SL.payload(body))
                 for w in SL.line_text(item).split()]
        words = [w for w in words if w]
        if len(words) >= DECOY_MIN_WORDS:
            out.append(words)
    return out


def _cookies() -> list[str]:
    """What $MILD_COOKIES says to sign in with, if it says anything.

    YouTube now asks a good share of unauthenticated downloads to prove they
    are not a bot, and there is no client or retry that talks it round -- a
    real session passed here does. Tested the same way for SoundCloud and it
    does NOT: a track SoundCloud serves through Go+ came back "DRM protected"
    with a genuine logged-in session exactly as it did with none, because the
    restriction is the subscription, not the anonymity, and yt-dlp has no way
    to decrypt that stream at any authentication level. Worth setting anyway
    -- it is the whole fix for YouTube's bot check, which is the more common
    wall -- just not a fix for a Go+ track.

    A browser name ("firefox", "chromium", "firefox:default") borrows that
    browser's cookies; a path to a cookies.txt is used as it is. Left unset,
    nothing is sent and nothing changes.
    """
    said = os.environ.get("MILD_COOKIES", "").strip()
    if not said:
        return []
    return (["--cookies", said] if os.path.exists(said)
            else ["--cookies-from-browser", said])


def _place(url: str) -> str:
    return "soundcloud" if "soundcloud.com" in url else "youtube"


def _named(url: str) -> str:
    """Short enough for a one-line reason, and still says which upload.

    A YouTube id is what comes after the `=`; a SoundCloud one is the last two
    path parts, account and slug, which is the readable half of the URL.
    """
    if _place(url) == "soundcloud":
        return "/".join(url.rstrip("/").split("/")[-2:])
    return url.rsplit("=", 1)[-1]


def _candidates(hits: list[tuple[str, float]],
                tries: int = FETCH_TRIES) -> list[tuple[str, float]]:
    """The few to actually try, with both places represented.

    SoundCloud sorts ahead of YouTube as a block, so the head of the list can
    be nothing but SoundCloud -- and when those turn out to be re-uploads that
    will not do, the YouTube copy that would have worked is never reached. One
    hit from whichever place is missing is added on the end rather than taking
    a slot off the front, because the front is where the good copy usually is.
    """
    picked = list(hits[:tries])
    seen = {_place(url) for url, _dur in picked}
    for url, dur in hits[tries:]:
        if _place(url) not in seen:
            picked.append((url, dur))
            break
    return picked


def fetch(url: str, path: str) -> str | None:
    """Audio from `url` as 44.1kHz stereo wav at `path`, or None.

    Full rate and both channels, unlike the mono 16kHz this used to fetch: the
    separation runs first now and it wants the mix as it was mastered. The
    aligner's own downmix happens in memory afterwards, so nothing is lost by
    handing it the better copy.

    Why it failed is left on `fetch.last_error`. It used to be thrown away, and
    a 403 on one upload then reached the user as "no copy at the right length"
    -- which sent them to check the one thing that was not wrong.

    The alternate player clients are YouTube's business and are only offered
    to YouTube. Retrying is for a door that might open on the next knock -- a
    403, a rate limit, a timeout. Two answers are not doors at all: YouTube's
    "sign in to confirm you're not a bot", and SoundCloud's own bot check --
    plenty of tracks that play free in a browser still 404 every transcoding
    an anonymous API request asks for, and come back looking exactly like DRM
    even though nothing about the track is gated. Both say the same thing
    however many times they are asked, so they are reported at once and the
    next hit is tried instead.
    """
    fetch.last_error = ""
    base = ["yt-dlp", url, "-f", "bestaudio/best", "--no-playlist",
            "--no-warnings", "--quiet", "-x", "--audio-format", "wav",
            "--postprocessor-args", f"ffmpeg:-ac 2 -ar {SEP_RATE}",
            "-o", path.rsplit(".", 1)[0] + ".%(ext)s"] + _cookies()
    tube = "youtube.com" in url or "youtu.be" in url
    try:
        for attempt in range(FETCH_RETRIES):
            cmd = list(base)
            if tube and attempt >= FETCH_RETRIES // 2:
                cmd += ["--extractor-args",
                        "youtube:player_client=" + ",".join(YT_CLIENTS)]
            try:
                subprocess.run(cmd, capture_output=True, timeout=600, check=True)
                break
            except subprocess.CalledProcessError as again:
                said = (again.stderr or b"").decode("utf-8", "replace")
                if _hard(said):
                    raise
                if attempt + 1 < FETCH_RETRIES and any(
                        x in said for x in ("403", "429", "Forbidden",
                                            "Too Many Requests", "timed out",
                                            "not available", "reloaded")):
                    time.sleep(RETRY_WAIT * (attempt + 1))
                    continue
                raise
    except subprocess.CalledProcessError as exc:
        said = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        fetch.last_error = (said[-1].replace("ERROR: ", "") if said
                            else f"yt-dlp exited {exc.returncode}")
        fetch.last_error = _hard(fetch.last_error) or fetch.last_error
        return None
    except Exception as exc:
        fetch.last_error = f"{type(exc).__name__}: {exc}"
        return None
    if os.path.exists(path):
        return path
    fetch.last_error = "yt-dlp reported success but wrote nothing"
    return None


fetch.last_error = ""


@contextlib.contextmanager
def fetched(query: str, length: float, where: str | None = None,
            artist: str = "", tid: str = "",
            words: list[str] | None = None,
            decoys: list[list[str]] | None = None,
            say: Callable[[str], None] | None = None):
    """A copy of the song for as long as the `with` block runs, and not a moment
    longer. Yields a path, or None if no copy could be had.

    Why not, in the caller's words, is on `fetched.last_error`. There are three
    quite different answers -- the search found nothing, it found nothing of
    the right length, or it found copies and none of them would download -- and
    they had all been reported as the middle one.

    `words` is the transcript this copy is meant to have -- pass it and a
    wrong recording that happens to share the right length is caught before
    it is trusted, cached and handed back on every run after. `decoys` is the
    other songs it is judged against; leave it out and `local_decoys` supplies
    some, so a caller only has to bring the one list it actually knows.

    `say`, if given, hears which candidate is being tried and that a copy is
    being checked -- a caller can otherwise wait the better part of a minute
    per candidate with nothing on screen to say why, which reads as hung
    rather than as thorough. Two or three candidates deep, with each of the
    first few blocked (YouTube's bot check, SoundCloud's own), is a couple of
    minutes with no sign of doing anything, and that is a real cost worth
    reporting rather than hiding.

    The delete is in a finally: an alignment that raises, times out or is
    interrupted still does not leave a copy of somebody's record behind.
    """
    tmp = where or os.path.join(tempfile.gettempdir(),
                                f"mild-align-{os.getpid()}.wav")
    if words and decoys is None:
        decoys = local_decoys(exclude=query)
    tell = say or (lambda _msg: None)
    got = None
    fetched.last_error = ""
    fetched.swapped = None
    fetched.margin = None
    fetched.doubted = None
    fetched.unverified = None
    try:
        saved = _kept(tid) if tid else None
        if saved:
            yield str(saved)
            return
        pinned = LS.pinned_source(tid) if tid else ""
        if pinned:
            for _try in range(PIN_TRIES):
                got = fetch(pinned, tmp)
                if not got:
                    continue
                if words and decoys:
                    mark = _sounds_like(got, words, decoys)
                    fetched.margin = mark
                    if mark is not None and mark < HEARD_MARGIN:
                        fetched.swapped = (pinned,
                                           f"a different recording "
                                           f"({mark*100:+.0f}%) -- refetching")
                        LS.pin_source(tid, "")
                        got = None
                        break
                yield got
                return
            if got is None and not fetched.swapped:
                fetched.swapped = (pinned, fetch.last_error or "download failed")
                LS.pin_source(tid, "")
        tell("searching SoundCloud and YouTube…")
        hits = find(query, length, artist=artist)
        if not hits:
            if not find.seen:
                fetched.last_error = "nothing found for that search"
            elif find.near:
                fetched.last_error = (
                    f"nothing at the right length — wanted {length:.0f}s, and "
                    f"the closest of {find.seen} was {find.near[0]:.0f}s "
                    f"({find.near[1]})")
            else:
                fetched.last_error = (
                    f"nothing at the right length — wanted {length:.0f}s, "
                    f"out of {find.seen} found")
        why = []
        best = None
        checked = bool(words and decoys)
        candidates = _candidates(hits)
        for n, (url, _dur) in enumerate(candidates, 1):
            tell(f"trying copy {n}/{len(candidates)} — {_named(url)}…")
            got = fetch(url, tmp)
            if not got:
                why.append(fetch.last_error or "download failed")
                continue
            if checked:
                tell("checking it's the right recording…")
                mark = _sounds_like(got, words, decoys)
                fetched.margin = mark
                if mark is not None and mark < HEARD_MARGIN:
                    why.append(f"{_named(url)} is a different "
                               f"recording ({mark*100:+.0f}%)")
                    if best is None or mark > best[0]:
                        best = (mark, url)
                    got = None
                    continue
            elif not find.mine.get(url, False):
                fetched.unverified = (
                    url, "not on the artist's own account, and no words "
                        "were given to check it against")
            if tid:
                LS.pin_source(tid, url)
                _keep(tid, got)
            break
        if not got and best is not None:
            got = fetch(best[1], tmp)
            fetched.doubted = best[0]
            if got and tid:
                LS.pin_source(tid, best[1])
        if hits and not got:
            fetched.last_error = (
                f"{len(hits)} copies at the right length, and "
                f"{'none of the ' + str(len(why)) if len(why) > 1 else 'the one'} "
                f"tried would download — "
                f"{'; '.join(dict.fromkeys(why))[:160] or 'no reason given'}")
        yield got
    finally:
        stem = tmp.rsplit(".", 1)[0]
        for leftover in (tmp, stem + ".webm", stem + ".m4a",
                         stem + ".mp3", stem + ".opus"):
            try:
                os.remove(leftover)
            except OSError:
                pass


fetched.last_error = ""
fetched.swapped = None
fetched.margin = None
fetched.doubted = None


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
