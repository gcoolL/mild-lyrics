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
import sys
import tempfile
import time
import unicodedata
import urllib.parse

import genius_roman as GR
import lyric_sources as LS
import noconsole
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

    An empty list means one of two things and `_genius_hits.last_error` says
    which: Genius answered and knows no such song, or it never answered at all.
    Four queries three attempts each are swallowed here by design -- one of
    them failing is ordinary and says nothing -- but ALL of them failing is the
    door being shut, and that is not something to hand back in silence. Set
    only when nothing got through: one query answering is Genius reachable,
    whatever the other three did.
    """
    got, seen, spoke, bad = [], set(), False, ""
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
                spoke = True
            except Exception as exc:                     # noqa: BLE001
                hits, bad = [], GR.why(exc, timeout)
            if hits:
                break
            if attempt + 1 < GENIUS_TRIES:
                time.sleep(GENIUS_WAIT * (attempt + 1))
        for hit in hits:
            res = hit.get("result")
            if isinstance(res, dict) and res.get("id") and res["id"] not in seen:
                seen.add(res["id"])
                got.append(res)
    _genius_hits.last_error = "" if spoke else bad
    return got


_genius_hits.last_error = ""


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

    None means "no document", and `genius_doc.last_error` says whether that is
    because Genius has no such song or because nothing here could reach it.
    Empty where the answer really is that Genius has not got it, so a caller
    can report a shut door and stay quiet about a miss.
    """
    genius_doc.last_error = ""
    title = str(meta.get("title") or "").strip()
    artist = str(meta.get("artist") or "").strip()
    if not title:
        return None
    try:
        hits = _genius_hits(token, title, artist, timeout)
    except Exception as exc:                             # noqa: BLE001
        genius_doc.last_error = GR.why(exc, timeout)
        return None
    genius_doc.last_error = _genius_hits.last_error
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
        if not LS._same_cut(f"{got.get('title') or ''} "
                            f"{got.get('full_title') or ''}", title):
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
    credit = ""
    try:
        credit = GR.credit_of(GR.song_of(token, best[1], timeout))
    except Exception:                                    # noqa: BLE001
        credit = ""
    try:
        marked = GR.voiced_lines(GR.lyrics_for(best[1], timeout=timeout,
                                               markup=True))
    except Exception:
        marked = []
    if not marked:
        try:
            plain = GR.clean_lines(GR.lyrics_for(best[1], timeout=timeout))
        except Exception as exc:                         # noqa: BLE001
            genius_doc.last_error = GR.why(exc, timeout)
            return None
        genius_doc.last_error = GR.lyrics_for.last_error
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
    out = {"Type": "Static", "_timing": "genius", "Content": content}
    if credit:
        out["_words_by"] = credit
    genius_doc.last_error = ""
    return out


genius_doc.last_error = ""


HOLD = 0.6

MIN_SYL = 0.02

# What a fetched copy is written at. It was the separator's rate, and the
# separator has gone; it stays because a file on disk has to be written at
# something and everything cached was written at this.
SEP_RATE = 44100

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
            got = noconsole.run(cmd, capture_output=True, text=True,
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
                noconsole.run(cmd, capture_output=True, timeout=600, check=True)
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

    `words` and `decoys` are taken and no longer used. They were the transcript
    this copy is meant to have and the other songs it was judged against, and a
    wrong recording that happened to share the right length was caught by
    listening to it. The thing that listened was the forced aligner's acoustic
    model, and that has been taken out of this program -- so a copy is now
    chosen on its metadata alone and `fetched.unverified` says so where nothing
    else vouches for it. The two arguments are still accepted because callers
    pass them and because the check is worth putting back if the model ever
    returns.

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
        candidates = _candidates(hits)
        for n, (url, _dur) in enumerate(candidates, 1):
            tell(f"trying copy {n}/{len(candidates)} — {_named(url)}…")
            got = fetch(url, tmp)
            if not got:
                why.append(fetch.last_error or "download failed")
                continue
            if not find.mine.get(url, False):
                fetched.unverified = (
                    url, "not on the artist's own account, and nothing here "
                         "can listen to it to be sure")
            if tid:
                LS.pin_source(tid, url)
                _keep(tid, got)
            break
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
