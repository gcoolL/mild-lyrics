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

# How confident a word has to be before its timing is used.
#
# This is set for SINGING, not speech, and the difference is large. The aligner
# is a speech model; over a dense mix its confidence collapses even where it is
# placing words correctly. Measured against a track whose word timings were
# already known: the median score was 0.048 while the median placement was
# within 0.14s of the known answer. A speech-shaped threshold of 0.3 kept 2
# words in 607 and threw away timings that were right.
#
# Separating the vocal first lifts those scores considerably -- that measurement
# was taken on the full mix -- but the floor stays where it is, because it was
# never doing the work of telling a good timing from a bad one. It only drops
# the truly hopeless. A check that the words run forwards was tried and removed,
# because CTC forced alignment is monotonic by construction: it dropped 0 of 166
# words, and the raw output stepped backwards 0 times in 186. The errors that
# remain are stretch and squeeze, where the text says more than the audio sings,
# and neither order nor confidence can see those. See the note at the foot.
MIN_SCORE = 0.005
# Neighbouring words closer together than this are not being sung, they are
# being caught up with. See _packed, where a song's share of them is the
# stretch-and-squeeze detector the note above says confidence cannot be.
PACKED_UNDER = 0.1
# Onset snapping (experimental, off by default -- see _onsets).
ONSET_HOP = 160           # 10ms at 16kHz, finer than a CTC frame
ONSET_NEAR = 25           # frames of neighbourhood a peak must stand above
ONSET_OVER = 1.4          # and by how much
ONSET_WINDOW = 0.12       # how far BACK a word start may be moved, in seconds
ONSET_FORWARD = 0.4       # and forward, as a fraction of that
ONSET_DOUBT = 2.0         # how much a later peak is doubted against an earlier
# Where the word's beginning is EXPECTED to be, relative to where CTC put it.
# CTC emits a token once it has heard enough of it, so the frame it fires on
# sits a few frames past the sound that started it -- measured at +0.060s on
# SHOWSTOPPER (438 words) and +0.064s on bipolar (114 words), flat across the
# thirds of both songs, so it is the model's habit and not either song's.
#
# This only AIMS the search; it never moves a word by itself. Scoring peaks by
# their distance from the model's own guess made the lateness self-sustaining:
# the true onset sits 0.06s behind and scores 0.06, while any spurious peak up
# to 0.03s AHEAD scores less and wins. That is why snapping used to remove only
# a seventh of the error -- it was measuring from the wrong point.
ONSET_BACK = 5            # frames a peak may walk back to the foot of its rise
# Both of the above, replayed over five songs with word-synced references --
# the share of words landing within 0.1s of one, before and after:
#
#   Havana                34% -> 51%      Deftones, Passenger    9% -> 19%
#   SHOWSTOPPER           78% -> 86%      bipolar               68% -> 75%
#   Phantom               90% -> 87%
#
# Phantom is the price and it is worth naming: CTC was already unbiased on it
# (+0.020s), so a fixed expectation of lateness overshoots and costs three
# points. Four songs gain seven to seventeen. A per-song estimate would be
# better than a constant and was tried -- measure the median distance from each
# word's guess back to the nearest onset -- but it answered 0.017 to 0.022 for
# every song alike, on songs whose real lateness ran from 0.030 to 0.224. It
# measures how dense the onsets are, not how late the model is.
ONSET_LATE = 0.06
# Whether a word that found no onset gets that lateness taken off anyway -- a
# narrower version of the flat lead below, which never touches a word an onset
# already spoke for. OFF: it moved SHOWSTOPPER two points and bipolar not at
# all, and of 384 settings swept offline none beat the shipping ones on both
# songs at once. Two points is inside the run-to-run spread measured on this
# machine, so this is "not shown to help", not "shown not to".
ONSET_LEAD_KEPT = False
# What is NOT here: a flat lead. Every song measures +0.07 to +0.13s late
# against the references, and snapping back to onsets only removes about a
# seventh of it, so subtracting the rest as a constant is the obvious next move.
# It was built, rendered three ways and listened to: on a fast syllabic run
# ("yabba-dabba-doo" and the lines after it) the version with 72ms taken off is
# audibly WORSE than the version without. A constant cannot be right when the
# error it is correcting is not constant -- dense syllables need the timing the
# model gives them. The remaining lateness is left alone deliberately.
# Below this share of the lyric's words heard anywhere in the audio, the
# recording is doubted rather than the alignment.
HEARD_SHARE = 0.35
# How far above the unrelated-songs floor a recording must sit to be believed.
# Provisional: seven songs is not a calibration, and every song played from
# here carries these numbers, so the distribution will say where this belongs.
HEARD_MARGIN = 0.15
# Below this, the unrelated songs share so little with the transcript that
# there is no scale left to measure a margin on -- a language mismatch, not
# a wrong recording.
NULL_FLOOR = 0.05
# The verifier only has to recognise words, not time them, so it uses a model
# small enough to fit beside everything else on the card.
VERIFY_MODEL = "openai/whisper-base"
# Ignored when asking whether a transcript is of these words: every English
# lyric contains them, so they raise the floor and the ceiling together and
# leave less room between the two.
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
# A word cannot sensibly run longer than this. The aligner will stretch one word
# across an instrumental break if the text says a word is there and the audio
# disagrees, and the result is a syllable that fills for eight seconds.
MAX_WORD = 4.0


# --------------------------------------------------------------------------
# the text frontend
#
# MMS_FA's entire vocabulary is 29 symbols: a-z, apostrophe, hyphen, star. It is
# multilingual not because it knows other alphabets but because it expects the
# text to arrive ROMANISED -- that is what uroman is for, and it is the half of
# the model's own design this file used to skip. `_flat` simply deleted anything
# outside [a-z'], so 無敵の笑顔 became "" and every Japanese, Korean, Cyrillic and
# Greek word was silently dropped before the aligner ever saw it.
#
# Romanising is only half of it, though. Japanese and Chinese lines carry no
# spaces, so `text.split()` hands back the whole line as one token, and one
# token gets one span -- which is line timing wearing a word's clothing. The
# line has to be cut into units first, and each unit romanised on its own so
# the timing can be put back on the characters it came from.
# --------------------------------------------------------------------------
# Kana, CJK ideographs and Hangul: the scripts that do not put spaces between
# words. SL.CJK covers the first two; Hangul is added because uroman handles it
# and the same segmentation problem applies.
UNSPACED = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿가-힣]")
# Kana, and only kana, is what says a line is Japanese rather than Chinese.
# pykakasi reads hanzi as if they were kanji, so 你好世界 came back "sekai" with
# 好 dropped on the floor -- a Japanese reading of a Chinese line, missing a
# character. Hanzi without kana goes to uroman, which gives pinyin.
KANA = re.compile(r"[぀-ゟ゠-ヿ]")
ASCII_OK = re.compile(r"^[a-z']+$")

_uroman = None
_kakasi = None
# Readings worked out while cutting a line up, kept for _flat to find later.
#
# The context is in the LINE, not the unit: 無敵 alone carries no kana, so asked
# on its own it romanises as Chinese and comes back "wudi" -- but the line it
# came from was 無敵の笑顔, plainly Japanese, and pykakasi already said "muteki"
# while segmenting it. Recomputing per unit threw that away. This is the one
# piece of state in the file; it is filled by words_of and only ever read.
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
            # One conversion, read twice. This asked pykakasi the same
            # question twice over -- once for the segmentation and once for
            # the readings -- and they come back in the same objects.
            try:
                got = list(_kakasi.convert(word))
            except Exception:
                got = []
            parts = [p.get("orig") or "" for p in got]
            reads = {p["orig"]: p["hepburn"] for p in got
                     if p.get("orig") and p.get("hepburn")}
            parts = [p for p in parts if p]
            # Only trust the segmentation if it accounts for every character.
            # pykakasi silently drops what its dictionary does not recognise,
            # and a unit list that does not rebuild the line would put the
            # timings on the wrong characters.
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
    # `_reading` belongs to the document being read, not to the process. It
    # was filled and never emptied, which is harmless for one song and is not
    # what this program does: the window aligns whatever plays, for as long as
    # it is open. Cleared here because this is the one place that fills it,
    # and _flat reads it back within the same alignment.
    _reading.clear()
    words: list[str] = []
    where: list[tuple[int, int, bool]] = []
    # _items, not payload["Content"]: an unsynced document keeps its lines under
    # "Lines" and leaves "Content" empty, and reading the wrong one found no
    # words at all -- on precisely the documents this is most worth doing, since
    # a song with no timing anywhere has everything to gain from an alignment.
    for li, item in enumerate(LS._items(SL.payload(doc))):
        text = SL.line_text(item) or ""
        _romanise("")                       # make sure _kakasi is decided
        wi, group = 0, 0
        for chunk, bg in _voices(text):
            # None for the lead, and a NUMBER for an ad-lib -- not a flag.
            # "(Baow) (What the fuck are you doing, Toxi?)" is two answering
            # voices, written apart and sung apart, and one flag folded them
            # into a single group that read as one long ad-lib.
            at = None
            if bg:
                at = group
                group += 1
            for w, joined in _units(chunk):
                words.append(w)
                where.append((li, wi, joined, at))
                wi += 1
    return words, where


# An ad-lib, as everybody writing lyrics down marks one: in round brackets,
# beside the line it answers. "(What?)", "(Huh?)", "(Facts)". Square brackets
# are section headings and are not this -- _flat already reduces "[Chorus]" to
# nothing, so they never reach the aligner either way.
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


# Genius keeps translations as separate songs, credited to a "Genius <language>
# Translations" account and titled with the language's own word for it. They
# search exactly as well as the original does -- asking for FE!N returned the
# Russian page, and the aligner timed "Просто выйди на улицу" against Travis
# Scott. is_romanization() does not catch these: a translation is not a
# transliteration, and its `language` field is the language it was translated
# INTO, which looks perfectly ordinary.
#
# Matching the artist credit is the reliable half -- that account naming is
# Genius' own convention and holds across every language. The title words are
# the second net, for hits that arrive without artist fields attached.
TRANSLATION = re.compile(
    r"(\btranslat|\btradu|\bübersetz|\bubersetz|\bvertaling|çeviri|ceviri"
    r"|tłumacz|tlumacz|fordítás|forditas|prijevod|превод|перевод|переклад"
    r"|翻訳|번역|翻译|譯|ترجمة|תרגום)", re.I)


def _bare(name: str) -> str:
    """A title without the parenthetical Spotify hangs off the end of it.

    "FE!N (feat. Playboi Carti)" searches worse than "FE!N" does, and the
    feature is in the artist field anyway.
    """
    out = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*", " ", name or "")
    out = re.sub(r"\s+-\s+(remaster|remastered|single|radio|album)\b.*$", "", out, flags=re.I)
    return out.strip() or (name or "").strip()


# How many times one search query is worth asking before its silence is
# believed, and how long to wait between -- see the note inside _genius_hits.
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
    # The primary artist alone, first. Spotify hands over every credited name
    # and searching all of them is actively worse: "FE!N Travis Scott, Playboi
    # Carti" returned a listening log, a guided meditation and four translation
    # pages, because those pages carry the whole credit in their titles and the
    # song itself does not. "FE!N Travis Scott" returns the song, first hit.
    lead = _bare(re.split(r"\s*[,&]\s*|\s+(?:feat|ft|with)\.?\s+", artist or "",
                          maxsplit=1)[0])
    # The primary artist FIRST, before any of the title-led forms. Genius'
    # search weighs the leading words hardest, so on a song only its own
    # audience has heard of, the title in front buries it under famous songs
    # that share the word: "SHOWSTOPPER ToxiPlays" found the song 0 times out
    # of 10 while "ToxiPlays SHOWSTOPPER" found it 10 out of 10, same minute,
    # same token. Case makes no difference; the order makes all of it.
    #
    # Added to the ladder rather than replacing it. The title-led forms are
    # there for a measured reason of their own -- see the note below on FE!N --
    # and every hit from every query still has to pass the proof further down,
    # so an extra query can only add candidates, never promote a wrong one.
    for query in (f"{lead} {first}".strip(), f"{first} {lead}".strip(),
                  f"{first} {_bare(artist)}".strip(), first):
        url = f"{GR.API}/search?{urllib.parse.urlencode({'q': query})}"
        head = {"Authorization": f"Bearer {token}"} if token else {}
        # Asked more than once, because giving up on one query silently
        # promotes the next, and the queries are not alternatives of equal
        # standing: the first two name the artist, the last is the bare title.
        # A dropped connection on an artist-led query leaves the bare title
        # answering for it -- other people's songs, none of which can pass the
        # proof below -- and a song whose Genius page exists reads as having no
        # lyrics at all.
        #
        # An empty answer is retried alongside a thrown one. That is cheap
        # insurance, not a measured failure mode: asked twenty times across
        # four spellings, this search never once disagreed with itself. What it
        # does do is answer a differently-ORDERED query differently, which is
        # handled above and not here.
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


# How alike two names have to be before they are the same act, and two titles
# before they are the same song. Both are needed now -- see genius_doc.
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
    # The reliable rule, and the reason this is not just a word list: Genius
    # files every translation and every romanisation under a house account
    # called "Genius <something>" -- Genius Russian Translations, Genius Brasil
    # Traduções, Genius Romanizations. No artist releases under that name.
    # "Traduções" is what showed the word list alone was not enough; it does not
    # contain "traduz", and the German and Turkish pages were caught while the
    # Brazilian one sailed through.
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
        # A romanisation is somebody else's transliteration of the song, not
        # the words it is sung in -- right for the romaji panel, wrong here.
        if not GR.is_song(hit) or GR.is_romanization(hit):
            continue
        got = hit.get("result") if isinstance(hit.get("result"), dict) else hit
        if _translation(got):
            continue
        sid = got.get("id")
        if not sid:
            continue
        # Genius search is generous; make it prove the hit is this song rather
        # than a remix, a cover or a track that merely shares a word.
        #
        # BOTH halves, where this used to take whichever agreed. "Either is
        # enough" was written for features -- Genius puts them in the title on
        # some songs and in the artist on others -- and what it actually meant
        # was that one perfect half excused any other. Searching ToxiPlays'
        # "LOSE MY NUMBER" scored a stranger's "bop it" at 1.00 on the title
        # and ToxiPlays' own "wordle freestyle" at 1.00 on the artist, so a
        # dozen hits tied at the top and the one that won was whichever the
        # search happened to return first. The feature problem is real and is
        # answered where it arises: _artist_alike reads every name Genius
        # credits, and _bare takes the feature back out of the title.
        tsim = GR.similar(GR.key(_bare(title)),
                          GR.key(_bare(str(got.get("title") or ""))))
        if tsim < TITLE_MIN:
            continue
        asim = 1.0
        if artist:
            asim = _artist_alike(artist, got)
            # The whole point. A song this artist does not have on Genius is a
            # song with no lyrics here -- not an invitation to take a more
            # popular one that happens to share a name.
            if asim < ARTIST_MIN:
                continue
        # Ranked on the two together so a near-miss on one has to be carried by
        # a real match on the other, rather than ignored.
        score = tsim + asim
        if best is None or score > best[0]:
            best = (score, int(sid))
    if best is None:
        return None
    # WHO SINGS EACH LINE, while we are here. Genius marks the singer with type
    # styling and declares what each style means in the section header --
    # "[Verse 1: RM, <i>RM & Jung Kook</i>, <b>j-hope</b>]" -- and no other
    # source in this program knows that at all. It costs nothing extra: the
    # same page, read without throwing the tags away.
    #
    # The WORDS are identical either way; only the credit is added. That is
    # checked rather than assumed -- voiced_lines applies clean_lines' filters
    # -- because a change to the text here would silently change what the
    # aligner times.
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
    # The shape an unsynced document takes here: lines with Text and nothing
    # else. words_of() reads them through line_text(), and to_document() puts
    # the measured timings back onto these same items.
    content = []
    for line, opposite in zip(marked, flags):
        item = {"Text": line["text"], "Type": "Vocal"}
        if opposite:
            item["OppositeAligned"] = True
        if line.get("who"):
            item["_who"] = line["who"]        # for anyone reading, not rendered
        content.append(item)
    return {"Type": "Static", "_timing": "genius", "Content": content}


# How long a word may be held past the frames the aligner was sure about.
#
# CTC does not say when a word stops sounding. It says which frames it was
# confident carried that word's characters, and over a sung vowel most of the
# frames in between are blank -- so the span it reports is the consonants, and
# the held note falls outside it. Measured over two aligned songs, 40% of the
# time inside a line landed in a gap between one word's end and the next one's
# start, with a median gap of 0.10s. On screen that is every word snapping shut
# early and the fill stuttering between them.
#
# So a word runs on until the next one starts. This cap is what stops that
# turning a genuine pause into an eight-second held syllable: past it, the word
# ends and the rest of the gap is silence, which is what it is. 85% of the
# real word-to-word gaps measured were under 0.3s, and the ones above this cap
# were instrumental breaks of 4 to 20 seconds.
HOLD = 0.6

# The narrowest a syllable may be drawn, in seconds -- one frame's worth of
# the aligner's own 20ms resolution, rounded up. Nothing on screen can be
# shorter than this and still be seen, and a zero-width piece would put two
# syllables on the same instant. Used by _fill, by to_document's overlap trim
# and by the syllable splitter, which is why it is here rather than repeated
# as a literal in the three of them.
MIN_SYL = 0.02

# --------------------------------------------------------------------------
# how long the singer actually held it
#
# HOLD above is a guess, and it was always described as one: CTC does not say
# when a word stops sounding, so every word is run on by a flat 0.6s and the
# real answer -- somewhere between 0.02s and eight seconds -- is not consulted.
# It cannot be consulted from the emission either. That is the shape of the
# model: a three-second "ahhh" is the letter a for a frame or two and then
# blank, blank, blank, because blank is what CTC emits when nothing NEW is
# being said. The vowel is still sounding and the model has stopped mentioning
# it.
#
# But we are holding the answer already. demucs has just separated the vocal
# and the stem is in memory, and a stem is loud exactly while somebody is
# singing. So the aligner is used for what it is good at -- finding the edge
# of a consonant, which it does to about a fifth of a second -- and the
# waveform is used for what it is good at, which is knowing whether there is
# still a voice there.
#
# Thresholds are taken from the song rather than fixed. A stem carries bleed
# and a mastered track can sit anywhere, so "quiet" means quiet FOR THIS
# RECORDING: the level a short way up from its own floor towards its own
# loudness, both read off percentiles of its own frames.
# --------------------------------------------------------------------------
VOICE_HOP = 0.01            # seconds per energy frame
# Where the line between silence and singing sits, as a fraction of the way
# from this stem's quiet level to its loud one, in dB.
VOICE_LEVEL = 0.15
# How long it has to stay down to count as stopped. Shorter than this and a
# stop consonant's own closure -- the silent moment inside "back" -- would end
# the word early.
VOICE_QUIET = 0.08
# The cap that HOLD used to be. Far more generous, because the energy is doing
# the work now and this only has to stop a runaway where the stem never goes
# quiet: a fade-out, a held pad bleeding through, a bad separation.
VOICE_MAX = 2.5


# A copy has to be this much longer than the track, AND open with this much
# silence, before the difference is treated as padding rather than as noise in
# somebody's encoder. Below it there is nothing worth correcting and a wrong
# correction is worse than none.
LEAD_MIN = 0.35

# A word is only asked to justify its length past this, so ordinary words --
# which are a sixth of a second here, median -- are never questioned.
SUNG_MIN = 0.8
# ...and it justifies it by being sung through. Half, not all: the VAD trims
# the quiet head and tail of a phrase, so a word that ends on a decaying note
# is legitimately part silence.
SUNG_SHARE = 0.5
# How much silence has to sit in FRONT of a long word before its start is
# moved to where the singing actually begins. Small, but not zero: the VAD
# clips the quiet attack of a phrase, so every word looks slightly late into
# its own span and moving on that would make everything start late.
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
        # The same threshold Voice uses, for the same reason: read off this
        # recording's own levels rather than an absolute dBFS, because a
        # quietly mastered song is not a silent one.
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
# where the singing actually is
#
# Voice above reads an RMS envelope off the stem and calls anything above a
# threshold "voice". It is cheap and it is right most of the time, and it is
# fooled by exactly what a vocal stem is full of: demucs' bleed, a reverb tail,
# a breath, the ring of a snare that did not separate cleanly. All of those are
# energy, none of them is a word, and a word held until the energy stops is
# held through all of them.
#
# Silero says whether a frame is SPEECH rather than whether it is loud. It is
# 463k parameters and runs on the processor in well under a second, which is
# the only reason it can be asked about every song -- the rest of this file is
# careful about the card precisely because nothing else here is that small.
#
# This is the piece WhisperX has that we did not. WhisperX itself will not
# install on this interpreter -- every release since 3.3.0 caps at Python 3.12
# or 3.13, and the one version pip can reach pins a ctranslate2 with no 3.14
# wheel -- and it would be the wrong shape anyway: it segments audio in order
# to run ASR on the pieces, and our words come from Genius rather than from
# ASR. What transfers is the idea that a forced alignment should not be free to
# put a word where nobody is singing.
# --------------------------------------------------------------------------
# Silence shorter than this inside a phrase is not a gap -- it is a plosive, a
# breath, or the closure in the middle of a held word.
VAD_MIN_QUIET = 0.20
# A region shorter than this is not a phrase.
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
                # Silero expects something like a normal recording level, and a
                # separated stem is usually well below one.
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
                # `start` is in a gap: the singing has already stopped.
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
    # A run of untimed words at either end has only one side to lean on, so it
    # borrows HOLD's worth of room outside the anchor and shares that. Pinning
    # them to the anchor instead -- which is what this did first -- gave every
    # one of them the same instant and a 20ms width, so a line beginning "And I
    # know" flashed its first word and vanished. Line-initial words are exactly
    # the ones CTC tends to miss, so this is the common case, not the corner.
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
        # How far this word may run on: to the next one at the most, and
        # otherwise until the singer stops. Without a stem to listen to this
        # is the flat HOLD it always was.
        limit = rows[i + 1]["t"][0] if i + 1 < len(rows) else end + VOICE_MAX
        if voice is not None:
            end = max(end, min(limit, voice.until(end, end + VOICE_MAX)))
        elif i + 1 < len(rows):
            # Run on to the next word, but never past the cap and never
            # backwards -- a neighbour that starts before this one ends is left
            # exactly as the aligner placed it.
            end = max(end, min(limit, end + HOLD))
        elif tail:
            end = end + min(HOLD, max(0.0, end - start))
        # IsPartOfWord means "joins the NEXT syllable with no space" -- see
        # spicy_lyrics.line_words and the renderer in lyrics_gui. This file
        # tracked the opposite fact, "follows the previous one", which is what
        # `where` carries and what the frontend knows while it is cutting a
        # line up. The two are the same information shifted by one, and not
        # shifting it put every space one place early: "Jafar's staff" was
        # drawn "Jaf ar'sstaff".
        #
        # Whole words hid this, because a document of whole words has the flag
        # false everywhere and the two readings agree. It showed the moment a
        # word was cut into syllables -- and it was already showing on every
        # Japanese line, as a stray space after the first unit.
        joins = bool(rows[i + 1].get("joined")) if i + 1 < len(rows) else False
        got = {"Text": r["word"], "StartTime": round(start, 3),
               "EndTime": round(max(end, start + MIN_SYL), 3),
               "IsPartOfWord": joins}
        if i + 1 == len(rows):
            # Where this word was MEASURED to end, before the hold ran it on.
            # to_document needs the difference: a hold may run over a gap that
            # is merely quiet, and must not run over one that another line's
            # words are sitting in. Private, and taken off again there.
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
        # Not "keep the part that fits". Timing half a line and dropping the
        # rest is the same loss in miniature -- the renderer draws a timed line
        # from its syllables and an untimed one from its text, so a line with
        # three syllables out of fourteen reaches the screen as those three
        # words and nothing else. That is "name" where the song sings "First
        # off, I love me a real nigga sayin' nothing that ain't on his name".
        # Whole or untimed, never part.
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
        # A word stage three divided arrives as several pieces rather than
        # one. The first piece inherits the word's own joining flag and the
        # rest are joined to it, which is exactly what the frontend already
        # does for an unspaced Japanese line -- so _fill, the hold, and the
        # document below need to know nothing about any of this.
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
    # The lead's last word is held on past where it was measured, because the
    # line stays lit until the next one starts and a word that blinks out
    # early looks wrong. An ad-lib is not lit that way -- it is a short thing
    # thrown over somebody else's line and then gone -- so it ends where it was
    # measured to end. On a one-syllable "(Uh)" the hold was most of it.
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
    # (first index, last index, when the stretch starts, when it ends). The
    # middle pairs are two measured lines; the ends are one measured line and
    # the edge of the song.
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
        # A flat cap is the wrong instrument here, and measuring said so: on
        # these songs nothing came near MAX_WORD, and the one word held past
        # two seconds was "Tox" sung across the end of a line -- which a
        # tighter cap would have thrown away for being exactly what it is.
        # Length cannot tell a sustained note from a stretched mistake.
        #
        # Silence can. A word is doubted for the part of itself that nobody is
        # singing through, so a held note keeps its length and a word smeared
        # across an instrumental loses the smear. Only with a VAD to ask --
        # the envelope is too easily fooled by bleed to be trusted with this.
        if isinstance(voice, Speech) and end - start > SUNG_MIN:
            sung = voice.covered(start, end)
            if sung < SUNG_SHARE * (end - start):
                # Both ends, not just the back. A long word that is mostly not
                # sung has one of two faults: it is being held through silence
                # that comes after it, which `until` fixes, or it was placed
                # before anyone started singing and stretched to reach them,
                # which only moving the START can fix. The second is what an
                # instrumental flourish in an intro does to a first line, and
                # it is invisible from the numbers alone -- a word held through
                # an intro and a genuinely screamed note are the same shape,
                # 85% of their line either way, and differ only in whether
                # there is a voice inside them.
                began = voice.since(start, end)
                if began - start > SUNG_LATE and end - began >= MIN_SYL * 2:
                    start = began
                end = max(start + MIN_SYL, min(end, voice.until(start, end)))
                if end - start < MIN_SYL * 2:
                    continue
        timed[i] = {"start": round(start, 3), "end": round(end, 3)}
        # The score floor and the word cap are asked about the WORD, before
        # its pieces are looked at: a word that failed either of them has
        # nothing worth dividing, and a word that passed does not become
        # doubtful because it has three syllables in it.
        if row.get("parts"):
            timed[i]["parts"] = row["parts"]
    if not timed:
        return None

    payload = SL.payload(doc)
    items = LS._items(payload)
    out, placed, heard_only = [], 0, 0

    # Every line's syllables, before any of them is compared with its
    # neighbours. Built in full first because the repair below is about PAIRS
    # of lines, and a loop that has only ever seen the lines above it cannot
    # make it: it does not know where the next line starts.
    raw = {li: _syllables(words, where, timed, li, voice)
           for li in range(len(items))}

    # Give the last word of each line back the room the hold took from the next
    # one. _fill runs every word on until the singer stops, up to VOICE_MAX,
    # and caps it at the next WORD -- but the last word of a line has no next
    # word to be capped by, so it runs on into the line below. That is a hold,
    # not a measurement: the aligner placed the word where it placed it, and
    # everything past that is the envelope being generous.
    #
    # Left alone it costs whole lines. The overrun pushes `floor` past the next
    # line's start, _unoverlap finds no room, and the line is dropped to
    # untimed -- five of them on this song, all of them lines the aligner had
    # placed perfectly well. Measured: 49 of 64 lines word-timed with the hold
    # unbounded, 54 with it capped here.
    lit = [li for li in sorted(raw) if raw[li]]
    for a, b in zip(lit, lit[1:]):
        head, tail = raw[b][0]["StartTime"], raw[a][-1]
        # Where the hold may reach. Normally the next line's first syllable --
        # but if lines the aligner never placed sit in between, their words are
        # somewhere in this gap, and a hold that fills it leaves them nowhere
        # to go. "Nigga, me too" was squeezed out exactly so: the line above it
        # was held right up to the line below, and _share_gaps then found a gap
        # of zero to put it in. Against a gap with lines waiting in it, the
        # holding line falls back to where it was measured to stop.
        stop_at = head if b == a + 1 else min(head, tail.get("_measured", head))
        if tail["EndTime"] > stop_at:
            tail["EndTime"] = round(max(stop_at, tail["StartTime"] + MIN_SYL), 3)
    for syls in raw.values():
        for s in syls or ():
            s.pop("_measured", None)

    # Where the line before this one stopped sounding. A line whose first words
    # were untimed borrows room before its first anchor (see _fill), and without
    # this that borrowing can reach back into the line above and leave two lines
    # lit at once.
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
            # The ad-libs of this line, as their own voice. Not held against
            # `floor`: it is there to stop two LEADS being lit at once, and an
            # ad-lib overlapping the line it answers is the whole point of it.
            # Only ever alongside a lead -- a Background group under a line
            # with no timing of its own has nothing to be background to.
            # No `voice` for an ad-lib, deliberately. The envelope says when
            # the STEM stops sounding, and the stem is one signal with both
            # voices in it -- so asked when a "(Uh)" has finished it answers
            # with the moment the lead finishes the line over the top of it.
            # Every ad-lib on this song ran on to within a breath of its
            # line's end that way: "Uh" held 3.8 seconds under a 2.0 second
            # line. Without it _fill runs the last word on by its own length
            # instead, which is a guess bounded by the word rather than by
            # somebody else's phrase.
            groups = []
            for gi in sorted({w[3] for w in where
                              if w[0] == li and w[3] is not None}):
                bgs = _syllables(words, where, timed, li, None, want_bg=gi)
                if bgs:
                    for s in bgs:
                        s.pop("_measured", None)   # private to the hold cap
                    groups.append({"Syllables": bgs,
                                   "StartTime": bgs[0]["StartTime"],
                                   "EndTime": bgs[-1]["EndTime"]})
            if groups:
                new["Background"] = groups
                # The line has to contain what is inside it.
                #
                # StartTime and EndTime were taken from the LEAD alone, a few
                # lines up, before the ad-libs of this line existed. That was
                # harmless while _asides could only place an ad-lib inside the
                # lead's own frames -- it could not stick out of a range it was
                # cut from. ADLIB_REACH gives it three seconds past the line's
                # end, and nothing widened the line to match: over 278 songs,
                # 3135 ad-libs ended up sounding after the <p> they belong to
                # had declared itself finished, by a median of 1.53s. A player
                # lighting a line and then sweeping its syllables has no
                # sensible reading of that.
                new["StartTime"] = min([new["StartTime"]]
                                       + [g["StartTime"] for g in groups])
                new["EndTime"] = max([new["EndTime"]]
                                     + [g["EndTime"] for g in groups])
                # The lead's own text, with the ad-libs taken out of it: the
                # renderer puts them back in brackets from the group above, and
                # leaving them here as well printed each one twice.
                lead_text = ADLIB.sub(" ", SL.line_text(item) or "")
                lead_text = re.sub(r"\s+", " ", lead_text)
                # An ad-lib taken out of the MIDDLE of a line leaves its space
                # behind against the punctuation that followed it: "Caveman
                # drop on them niggas (Brr), yabba-dabba-doo" came back as
                # "niggas , yabba". The ad-lib is gone from the lead's text, so
                # the gap it sat in should close too.
                new["Text"] = re.sub(r"\s+([,.!?;:])", r"\1", lead_text).strip()
        elif li in (spoken or {}):
            # CTC placed nothing here, and the speech model did. Take its
            # times for the LINE -- not for the words, which it never had, so
            # this line is line-timed in a word-timed document and the renderer
            # already draws that: a <p> with times and plain text inside it.
            #
            # A measurement from the other model, not a guess between
            # neighbours. Worth taking because the alternative is a line that
            # never lights at all, and the two disagree by a syllable or so
            # where both of them answer.
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
    # Provenance splits the same way the graft's does: our words, their clock.
    doc2["_timing"] = "align"
    # How many lines are line-timed rather than word-timed, for the caller to
    # say so out loud. A document that is 90% word-timed and 10% line-timed is
    # not the same thing as one that is 90% word-timed and 10% dark, and the
    # count is the only way to tell them apart from outside.
    doc2["_heard_only"] = heard_only
    doc2["_shared"] = shared
    # Whether this walk was pinned, and on how many lines. An unanchored walk
    # is stretched around anything it cannot skip -- it starts tens of seconds
    # late and converges by the end -- so a document that does not carry this
    # cannot be told apart later from one that simply aligned badly.
    # Two numbers that need no reference, computed from what is already here.
    #
    # The per-word floor above only drops the hopeless; its own comment says the
    # errors left are stretch and squeeze, "and neither order nor confidence can
    # see those". Individually, no -- but a song's WORTH of them is visible.
    #
    # `_packed` is the share of neighbouring words placed under a tenth of a
    # second apart. Nobody sings ten words a second, so a walk that has stretched
    # early and must catch up shows as a crowd of impossible durations at the
    # end. Measured: healthy songs 2-10%, damaged ones 19-42%.
    #
    # `_score` is the median CTC score across the song. The floor uses it per
    # word and the aggregate was computed and thrown away, which is why none of
    # tonight's failures could be re-examined for it.
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
    # How many words an onset spoke for, which is the difference between "the
    # detector works on this mix" and "this mix has no attacks in it" -- and
    # those two want opposite fixes.
    doc2["_snapped"] = getattr(_snap, "found", None)
    doc2["_words"] = getattr(_snap, "total", None)
    # Where the two models disagree about a word. `_phone_apart` is the strong
    # form -- the phoneme pass put the word somewhere that barely overlaps
    # where the character pass put it -- and `_phone_gap` is how far apart they
    # are on the words they do agree overlap.
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
# fitting in the card
#
# Two numbers decide everything below: how much VRAM is free right now, and how
# much of it a stage would want. Neither model has a fixed appetite -- both work
# through the song a window at a time, and the window is what costs. So the
# question is never "does this fit", it is "how much may this hold at once, and
# is that still enough to be worth doing on the GPU at all".
# --------------------------------------------------------------------------
GB = 1024 ** 3

# (fixed GB, GB per second of the window) for each stage.
#
# Measured rather than guessed, on an RTX 4060 with torch 2.13/cu130, against
# what the DRIVER says this process holds -- not what the allocator reserved,
# which is about 0.12 GB short of it and is not the number the rest of the
# machine feels:
#
#     demucs htdemucs   2.0s segment  0.84 GB     7.8s segment  0.88 GB
#     MMS_FA            8.0s window   1.81 GB    30.0s window   3.36 GB
#
# The surprise is demucs, and it is worth writing down: its appetite barely
# moves with the segment at all -- 0.007 GB per second -- because with split=True
# the GPU only ever holds one segment while the assembled output stays on the
# CPU. An earlier guess of 0.35 GB per second was four times over, which cost
# nothing in safety and quite a lot in usefulness: it sent demucs to the CPU on
# any card with under 3.6 GB spare, when it would have fitted in under one.
#
# What is here is the measurement plus about a quarter for margin, since these
# are one card and one version of torch. `_shrinking()` is the safety net for
# where that margin is not enough.
DEMUCS_COST = (1.1, 0.02)
ALIGN_COST = (1.6, 0.08)

# The longest and shortest window each stage may work in, in seconds of audio.
# Demucs' ceiling is htdemucs' own training segment; going past it is not a
# memory question but a quality one, and the model's own figure wins if it
# disagrees. The aligner's ceiling is chosen rather than given: attention is
# quadratic in the window, so past about half a minute the cost climbs faster
# than the benefit, and the seam between windows is handled by overlapping them.
DEMUCS_WINDOW = (2.0, 7.8)
ALIGN_WINDOW = (8.0, 30.0)

# What is left on the card for everybody else, whatever we work out we need.
# A desktop with a compositor, a browser and a music player on it is already
# holding a few hundred megabytes and will ask for more without warning.
SPARE = 1.0
# The least _cap will ever reserve for us, in GB and as a share of the card.
# A card so busy that `free - SPARE` comes out at nothing would otherwise have
# us set a ceiling of zero and fail on the first allocation, when what we want
# is to try small and let _shrinking() take us to the CPU if it will not go.
CAP_FLOOR = 0.5
CAP_LEAST = 0.05

MODEL = "htdemucs"          # demucs' own default, and the best of them
RATE = 16000                # what the aligner works at
SEP_RATE = 44100            # what demucs works at


def _say(log: Callable[[str], Any] | None, msg: str) -> None:
    if log:
        log(msg)


# Whether to narrate. Read by _emission, which otherwise reports one window in
# four -- fine for a progress line, useless for watching where a stage is.
_LOUD = False

# --------------------------------------------------------------------------
# not taking the machine down with us
#
# Every stage here has a CPU path, and the CPU path is not merely slower -- it
# is slower AND it takes the whole processor while it is being slower. Whisper
# on the CPU ran a 124s song for 374 seconds at full tilt on every core and
# 7.5 GB resident, on a machine that was also running the player. That is not
# a fallback, it is a denial of service against the person who asked for it,
# and it took a desktop down.
#
# Two limits, both deliberately blunt. Leave the machine some cores, and do not
# put the OPTIONAL stage on the processor at all unless asked: anchors improve
# an alignment that already works, so "no anchors" is a real answer and six
# minutes of full load is not.
# --------------------------------------------------------------------------
# Cores left for everything else -- the desktop, the player, the browser the
# user is reading this in.
#
# Worth knowing what this does and does not do. torch already holds itself to
# the PHYSICAL cores, which on a 16-thread machine is 8 -- the "50% CPU" a
# stage on the processor shows is that, working exactly as intended. So this
# only bites where a build would take more, and it is not what keeps the
# machine alive. The opt-in below is.
SPARE_CORES = 2
# What a stage on the processor needs free before it is allowed to start, in
# GB. Whisper on the CPU measured 7.5 GB resident on a 124s song; this is that
# with room to be wrong, and it is checked against MemAvailable rather than
# free memory because the page cache is not an obstacle.
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
        # Never raise it -- torch's own default is already a considered figure
        # on most builds, and this exists to take cores away, not to add them.
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
        # A driver that is present but wedged, a card that has fallen off the
        # bus, CUDA built against another driver version. All of them mean the
        # same thing here, which is: use the CPU.
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
            # These two stages are not optional the way the anchors are -- there
            # is no alignment at all without them -- so the CPU stays their last
            # resort. It is held to most of the cores rather than all of them,
            # so the machine it is running on stays usable while it works.
            _say(log, f"  {what}: out of VRAM at {lo:.1f}s — finishing on the "
                      f"CPU, on {_threads()} of {os.cpu_count()} cores")
            device, window = "cpu", hi


# --------------------------------------------------------------------------
# audio in
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
# stage one: the vocal on its own
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
    # The model's own segment is the ceiling: asking for more than it was
    # trained on is a quality question rather than a memory one, and this is
    # only ever trying to use less.
    window = min(window, float(getattr(model, "segment", DEMUCS_WINDOW[1]) or
                               DEMUCS_WINDOW[1]))
    # Demucs is trained on loudness-normalised input and separates visibly worse
    # without this; the same scaling is undone on the way out so the stem comes
    # back at the level it went in at.
    ref = wave.mean(dim=0)
    mix = (wave - ref.mean()) / (ref.std() + 1e-8)

    def work(dev, seg):
        _stop(stop)
        _say(log, f"  demucs {name} on {dev}, {seg:.1f}s at a time")
        kw = dict(device=dev, split=True, overlap=0.25, shifts=0, progress=False)
        try:
            got = apply_model(model, mix[None], segment=seg, **kw)
        except TypeError:
            # Older demucs takes the segment off the model rather than the call.
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
        # Order matters: the model has to be unreferenced before the cache is
        # emptied, or its weights are still resident and the aligner starts a
        # gigabyte down.
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
# stage two: where our words land in it
# --------------------------------------------------------------------------
# What the aligner's dictionary can actually take. Everything else has to be
# folded into it or dropped, and dropped words still have to keep their place in
# the caller's list -- the timings are matched back up by index.
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
    # Nothing survived, so this is not written in the alphabet the model reads.
    # Romanise it rather than dropping it -- that is what the model expects and
    # is the difference between timing a Japanese song and timing none of it.
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
            # Back to probabilities before they are merged. forced_align scores
            # a token by its LOG probability, and MMS_FA's own aligner hands
            # back the exponent of that -- so leaving these as logs gives every
            # word a negative score, and to_document's floor (0.005) then
            # rejects the entire song as "most likely the wrong recording".
            # The old program exponentiates at the same point, for the same
            # reason.
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
        # Frames per sample for THIS window rather than a constant: the
        # convolutional front end drops a fraction of a frame at each edge, and
        # the last window is a different length from the rest.
        per = (hi - lo) / max(1, got.shape[0])
        a = int(round((at - lo) / per))
        b = int(round((min(n, at + step) - lo) / per))
        parts.append(got[a:max(a + 1, b)])
        at += step
        # One window in four is a progress line. Every window is a trace, and
        # the difference matters when the question is which window is slow.
        if len(parts) % (1 if _LOUD else 4) == 0:
            _say(log, f"  {what}… {min(at, n) / RATE:.0f}s of {n / RATE:.0f}s")
    out = torch.cat(parts, dim=0) if len(parts) > 1 else parts[0]
    return out, n / RATE / max(1, out.shape[0])


# --------------------------------------------------------------------------
# anchoring -- OFF BY DEFAULT since it was measured
#
# Seventeen songs, each aligned twice, once with this stage and once without:
# anchors won 0, tied 17, lost 0. Six of those songs were failing badly, which
# is the case this stage exists for, and it rescued none of them. Thinning one
# song's 32 anchors down to 1 changed its error by 0.028s -- in the free walk's
# favour -- so even good anchors were not doing work.
#
# The harm was not symmetric. Papa Roach sat at 22-30s in every measurement of
# a long day and aligns at 0.168s with the stage off; wifiskeleton went 14.628s
# to 0.099s. In both, the speech model placed a whole set of anchors tens of
# seconds from where the words are, and a monotonic walk has to reach them.
#
# The evidence that justified this stage (below) was collected when anchors
# came from a donor document, and the donor is gone -- see _anchor_points. The
# argument was never re-measured against _model_points, and does not survive it.
#
# Left in, reachable with anchors=True, because the reasoning below is sound
# for a source of anchors that is actually right, which a donor sometimes was.
#
# CTC forced alignment is monotonic and must consume every word it is given.
# That is what makes it trustworthy where the text and the recording agree,
# and it is exactly what breaks where they do not: hand it a line the song
# does not sing at that moment -- an instrumental drop, a repeated chorus
# taken from the wrong repeat -- and it cannot skip. It stretches the words
# around the hole to cover it, confidently, and one line ends up spanning
# twenty-four seconds of a track that is not singing any of it.
#
# Measured on "Fading Wind" against a line-synced copy of the same song: 53%
# of the scorable lines sat more than a second from the song's own median
# offset, 38% more than three, with single lines held across 10 to 24 seconds
# while the median line ran 2.2s. The median offset itself was +0.09s, so this
# is not the wrong recording and not a clock that needs shifting -- it is the
# alignment wandering inside a song it is otherwise placed correctly in.
#
# So: do not walk the whole song in one pass. Walk it between points already
# known to be right. A line pinned at both ends cannot be stretched across a
# break, because the frames either side of it are not the segment's to spend.
#
# The points come from a document somebody has already line-synced -- the same
# NetEase and LRCLIB entries the chain reads anyway, and which exist for
# precisely the songs this aligner is used on, since a song with word timing
# already does not come here. Their clock is not ours: they are timed against
# the streaming master and this is timed against a copy fetched from
# elsewhere. That is what the first pass is for. It is run exactly as before,
# its line starts are compared with the donor's, and the median of those
# differences is the constant between the two clocks -- measured rather than
# assumed, from our own reading of this very audio.
#
# Then the median is the thing to trust and the individual lines are not. A
# line the first pass put sixteen seconds out drags its own difference far
# from the median and no further: a median over dozens of lines does not move.
# Which is the whole trick -- the first pass is wrong in a minority of places
# and right about the offset, so it can be used to calibrate the donor without
# being believed line by line.
# --------------------------------------------------------------------------
# Enough matched lines to believe two documents are the same performance and
# to take a median offset from. Below this the median is not a median.
ANCHOR_MIN = 6
# ...and matching by TEXT is not enough to say so. This is the check that
# cost the most to learn and the one that matters:
#
# NetEase has a line-synced "Fading Wind" whose words are this song's exactly
# -- all 37 lines pair -- and whose times belong to a different, shorter edit
# of it. Its first line sits at 44.4s where this recording sings it at 9.3s,
# and its last at 216.8s where this one is still going at 282s. Anchored on
# that, every line was dragged into the back half of the song and the result
# was far worse than no anchoring at all.
#
# Two clocks for one recording differ by a constant. Two clocks for different
# edits do not, and that is visible without knowing which is which: take the
# difference for every matched line and see whether they agree. Measured over
# sixteen aligned tracks, the split is not close --
#
#     a real line-synced copy of this recording   79, 81, 84, 86, 89%
#     the same lyrics timed against another edit   3, 7%
#
# -- so the gate goes between them, and the one ambiguous case (42%) is
# refused, which costs a single pass and no more.
ANCHOR_TOL = 1.5
ANCHOR_SHARE = 0.6
# How much faster than its own average a stretch of song may be asked to be
# sung before the anchor around it is disbelieved.
#
# Anchors pin the lines the donor HAS. Lines it does not have -- a repeated
# verse it writes once and Genius writes twice -- fall between two anchors and
# have to fit in the gap, and if the gap is not big enough they are crushed
# into nothing and lost. "Gravity" lost thirteen lines that way: the donor has
# 51 where Genius has 62, and the missing ones landed in a gap sized for one.
#
# So a segment must have room to be SUNG, not merely room to hold one frame
# per character. The pace comes from the song's own first pass rather than a
# constant, because a rapper and a ballad differ by more than any figure that
# could be written here. Where the room is not there the anchor is dropped and
# the segments either side become one, which is where this started.
ANCHOR_AGREE = 0.75       # seconds an anchor may differ from the consensus
ANCHOR_SHIFT = 2.0        # how far the whole set may sit from the walk
ANCHOR_AGREE_MIN = 3      # anchors that must agree before any is believed
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
    # Whether these two are the same song at all is _pair's question, and it
    # already answers it properly -- sequence matching over the lines, so a
    # donor that splits or merges them differently still lines up, and a
    # rejection when too little of it matches. A chorus sung four times is
    # matched in order, which is the one way text alone can tell repeats apart.
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
    # Do these two clocks differ by a constant? If they do not, this is a
    # different edit of the song and its line times mean nothing here.
    agree = sum(1 for x in delta if abs(x - shift) <= ANCHOR_TOL)
    if agree < ANCHOR_MIN or agree < ANCHOR_SHARE * len(delta):
        _say(log, f"  a line-synced copy matched the words but not the clock "
                  f"({agree} of {len(delta)} lines agree) — it is timed against "
                  f"another edit, so one pass")
        return []
    # Every matched line becomes an anchor, not just the ones the first pass
    # agreed with. Dropping the disagreements is what the graft does, because
    # there a disagreement means the pairing is suspect -- here, past the gate
    # above, it usually means the first pass is wrong just there, which is the
    # case this exists to repair. The median is what makes that safe.
    return sorted((i, when[i] - shift) for i in when)


# --------------------------------------------------------------------------
# anchors from a model, rather than from somebody else's document
#
# _anchor_points above needs a stranger to have line-synced this exact song,
# and asks a provider chain for one by title and artist. On "LOSE MY NUMBER"
# that chain returned a different song of the same name -- NetEase's, credited
# to five songwriters none of whom are the artist -- and the words did not
# pair, so anchoring was refused and the whole song went through in one
# monotonic pass. Which is the failure this was built to prevent, arriving by
# the route that was supposed to prevent it.
#
# The premise was wrong. A donor is a guess about who else has timed this
# recording; the recording itself is right here, and a speech model will say
# where the words are in it without being asked about anybody's metadata. So
# the anchors come from listening now, and the only document in the run is
# Genius' -- which is the one that is reliably about the right song.
#
# Two things fall away with the donor, and both were only ever there to cope
# with it. The median shift: a donor is timed against the streaming master and
# we align a copy fetched from elsewhere, so the two clocks differ by a
# constant that had to be measured. ASR runs on OUR audio, so there is no
# constant -- what it heard at 41.8s was sung at 41.8s. And the clock-agreement
# gate, which existed to catch a donor timed against a different edit: there is
# no other edit here, only this file.
#
# What does NOT fall away is that the model mishears. It is asked for times
# and never for words -- the same discipline the donor was held to -- and its
# words are used only to find which of OUR words it was hearing. A mishearing
# fails to match and yields no anchor, which costs one pin out of dozens.
# Measured on this song: 332 of 485 words matched, giving 55 anchors across 64
# lines, monotonic throughout.
# --------------------------------------------------------------------------
# Small is enough and is the largest that fits beside everything else. medium
# was tried first and ran the card out of memory on the cross-attentions that
# word timestamps are read from -- they are the expensive part, not the
# weights, so this is not a size that can be bought back with a smaller batch.
ASR_MODEL = "openai/whisper-small"
# Measured on the same machine as the three above, and read differently from
# any of them:
#
#     whisper-small, word timestamps    30s  2.35 GB   60s  2.46 GB   124s  4.19 GB
#
# The others are billed per WINDOW, because a window is what they hold and the
# window is ours to choose. This one is billed per SONG. Whisper chunks the
# audio itself, at 30s, and that is not where the memory goes: word timestamps
# are read from the cross-attentions, and those are kept for the whole decode.
# So the figure to fit on the card is set by the length of the track, and a
# window would say a six-minute song costs what a thirty-second one does.
#
# Which is why align() passes the song's own duration as the window. The pair
# below is a straight line through the ends of that measurement -- the middle
# point sits under it, so the fit is generous where it is wrong -- plus a few
# per cent. Small next to the quarter the CTC stages carry, and it can afford
# to be: this stage has a CPU to fall back to and nothing depends on it.
ASR_COST = (1.9, 0.021)
# A window again, now that the decode is chunked: the least and most audio
# worth holding at once. room() picks the size from what the card actually has,
# the same as the two CTC stages -- a fixed 120s asked for 4.4 GB and was
# refused on a card with 3, which is a chunk size the machine could have
# managed twice over at 60.
ASR_WINDOW = (30.0, 120.0)
# How much song to decode at once.
#
# The cost above is per SECOND OF SONG, and it is real: word timestamps are
# read from the cross-attentions and those are kept for the whole decode. Left
# whole, a six-minute track asks for 9.5 GB and is refused by a card that could
# have done it in pieces -- "Rap God" is 364s, which is where this was noticed.
# So the song is decoded in chunks and the cost is per chunk, which makes the
# longest track cost the same as this one.
#
# The overlap is thrown away from the LATER chunk, so a word straddling a seam
# is kept once, at the reading of whichever chunk saw its beginning.
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
            # device=-1: build it on the CPU, always, and let heard() move it.
            #
            # Left to itself the pipeline puts the weights straight on the card
            # while it builds -- and by the time this is called _cap() has
            # already held our allocator down to what room() budgeted for the
            # STAGE, which is less than a gigabyte on a busy card. Loading then
            # failed against our own ceiling, the whole model was written off
            # as unavailable, and every song went through unanchored with one
            # line in the log to say so. Building here costs nothing: the model
            # has to be moved per call regardless, because it must not sit on
            # the card while demucs and MMS_FA are using it.
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
        # With the reason. "Could not be loaded" on its own sent this looking
        # at the network for what turned out to be our own VRAM ceiling.
        _say(log, f"  {name} could not be loaded ({_asr.last_error or 'no reason given'})"
                  f" — one pass")
        heard.why = f"{name} could not be loaded"
        return []
    _stop(stop)
    wave = _resample(_channels(wave, 1), rate, RATE)
    audio = wave[0].numpy().astype("float32")
    got = None
    # The card, and the CPU only if the caller has said it may.
    #
    # This used to fall back on its own, on the reasoning that slow and right
    # beats fast and unanchored. That was wrong about the cost. A 244M-parameter
    # seq2seq decoding a whole song for word timestamps took 374 seconds on the
    # processor against 22 on the card -- seventeen times, at full load on every
    # core and 7.5 GB resident, while the player it was meant to be helping was
    # still running. It crashed the machine it was running on. Whatever else
    # this stage is, it is optional: without it the aligner does what it did
    # before anchors existed, which is a complete answer.
    #
    # So the CPU is opt-in and says how long it will take when it is taken.
    ladder = [device]
    if device != "cpu" and on_cpu:
        ladder.append("cpu")
    elif device != "cpu":
        ladder.append(None)                # a marker: say why, and stop
    for dev in ladder:
        if dev is None:
            _say(log, "  no room on the card for the speech model, and the "
                      "processor would take minutes — going on without anchors "
                      "(--asr-cpu to run it there anyway)")
            # Only if nothing was actually tried. This marker is the LAST rung
            # of the ladder, so it is reached both when the card was never an
            # option and when the card was tried and failed -- and it used to
            # overwrite the real reason with a guess about room, which sent me
            # looking at VRAM while 3.3 GB was free.
            heard.why = heard.why or "no room on the card for the speech model"
            break
        # Asked for the processor is not the same as there being room for it.
        # The run this guard exists for took the machine down rather than
        # itself: a stage that will not fit is refused here, where refusing
        # costs the anchors, instead of by the kernel, where it costs the
        # session.
        if dev == "cpu":
            spare = _ram_free()
            if spare and spare < CPU_RAM_NEEDED:
                _say(log, f"  the speech model wants about "
                          f"{CPU_RAM_NEEDED:.0f} GB on the processor and there "
                          f"is {spare:.1f} GB to be had — going on without "
                          f"anchors")
                break
        try:
            # Both, or neither. The pipeline keeps its OWN idea of where the
            # work happens and moves the audio there; move the weights alone
            # and it feeds a CUDA tensor to a CPU convolution. That is what the
            # CPU fallback did on its first outing -- the retry that exists for
            # when the card is full could never itself run.
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
                    # Everything is on the chunk's own clock; put it back on
                    # the song's, and drop what the previous chunk already saw.
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
        # Distinct from hearing nothing. An empty list used to mean both "this
        # audio has no words in it" and "the model never ran", and the verify
        # check below reads the second as evidence about the recording -- five
        # songs were reported as possibly-wrong when the card was simply full.
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
    # A line is pinned by the first of its words the model actually caught,
    # not by its first word: line-initial words are exactly the ones both this
    # and CTC tend to miss, and a line pinned by its second word is pinned a
    # syllable late rather than not at all.
    first: dict[int, float] = {}
    span: dict[int, tuple[float, float]] = {}
    for n, (line, _wi, _joined, bg) in enumerate(where):
        # A line is pinned by its lead. An ad-lib often comes in before the
        # line it answers, so pinning on one puts the anchor early and the
        # whole segment with it.
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
    # Monotonic or it is not usable: _anchored walks segments between these and
    # a pair that goes backwards would make two segments overlap. Whisper
    # occasionally hands back a timestamp behind the one before it around a
    # chunk seam, and one such pin is not worth losing the rest over.
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
# one line at a time, and then the pairs that argued
#
# The walk above is one pass over the whole song, and its strength is also its
# weakness: CTC must consume every word in order, so the lines cannot come out
# in the wrong order -- and a line placed badly pushes the error into the next
# one, which pushes it into the one after. Anchors bound how far that can
# travel; they do not stop it.
#
# The other way round: time each line on its own, in a window around where it
# is expected, and nothing that happens to one line can reach another. What is
# lost is the guarantee. Two lines timed separately can overlap, or swap.
#
# So the overlaps are repaired afterwards, and only they: where two lines argue
# about the same audio, the pair is timed AGAIN as one piece, which puts them
# back in order because a single walk cannot do otherwise. One pass of that,
# not a loop -- lines really can overlap in a song (a phrase begun over the tail
# of the one before it), and a loop would keep pulling those apart until
# something else broke.
# --------------------------------------------------------------------------
# How much room a line is given around where it is expected, in seconds.
LINE_PAD = 1.5
# How much two lines may overlap before they are considered to disagree, in
# FRAMES. A seam is not an argument.
LINE_TOUCH = 5


# How far past its own line's end an ad-lib may be looked for, in seconds, and
# how much worse than the walk's answer the new placement may score before it
# is refused.
# How far PAST its own line's end an ad-lib may be looked for, in seconds.
#
# Nothing, until this was measured. _asides walks each ad-lib inside exactly
# the frames its lead occupies, so an ad-lib could not be placed after its line
# ended however plainly it was sung there -- and an ad-lib that answers the
# line it follows is the ordinary case, not the exception. With nowhere later
# to go, CTC put them as early as the window allowed: across 18 songs the
# ad-libs came in a median 0.90s EARLY, 84% of them more than 0.3s early
# against 10% late, and only 6% landed within 0.3s.
#
# Forward only. The measurement says early, so reaching backwards as well
# would widen the search in the one direction that is already wrong.
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

    # Where each line is expected. The speech model where it heard one, the
    # walk otherwise -- two estimates of the same thing, and the one that did
    # not come from the walk is the better bound on the walk's own mistakes.
    est: dict[int, int] = {}
    for li in order:
        at = heard.get(li)
        if isinstance(at, (int, float)):
            est[li] = max(0, int(at / per_frame))
        else:
            got = [spans[n][0].start for n in lines[li] if spans[n]]
            est[li] = min(got) if got else 0
    # Expected pace, for how much room a line's own characters need.
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
        # Up to the next line's own estimate, so a line is not asked to find
        # itself inside the one after it.
        nxt = est[order[k + 1]] if k + 1 < len(order) else frames
        f0 = est[li] - pad
        # Up to where the NEXT line is expected, and no further. Reaching past
        # it -- which the first version of this did, by a padding -- lets the
        # line spread into its neighbour: every pair in the song then overlaps,
        # every pair is re-timed together, and what comes out is the whole walk
        # again in pieces. Enough room for the line's own characters at twice
        # the song's pace, whichever is smaller.
        f1 = min(max(nxt, f0 + need), est[li] + int(need * pace * 2) + pad)
        got = walk(ns, f0, f1)
        if got is None:
            continue
        placed[li] = got
        for n, sp in zip(ns, got):
            out[n] = sp

    if not placed:
        return None

    # One pass over the pairs that now argue. Timed together, which is the only
    # thing that reliably puts two lines back in order.
    fixed = 0
    done = [li for li in order if li in placed]
    for a, b in zip(done, done[1:]):
        left = [sp for sp in (out[n] for n in lines[a]) if sp]
        right = [sp for sp in (out[n] for n in lines[b]) if sp]
        if not left or not right:
            continue
        # By more than a hair. Two lines timed apart will touch at the seam
        # almost every time -- the end of one word and the start of the next
        # are the same instant, give or take a frame -- and treating that as a
        # disagreement re-times every pair in the song, which is the whole walk
        # again in pieces and worse than either.
        if left[-1][-1].end <= right[0][0].start + LINE_TOUCH:
            continue                       # they agree; nothing to settle
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
        # Said out loud, and at some cost to learn why. This swallowed a
        # NameError in _model_points for a while and the only symptom was that
        # every song quietly went through in one unanchored pass -- lines
        # drifting seconds out with nothing in the log to say the anchors had
        # never arrived. A stage that silently does nothing is the hardest kind
        # of bug in this file, and this is the second time: see _anchor_points.
        _say(log, f"  the anchors could not be worked out "
                  f"({type(exc).__name__}: {exc}) — one pass")
        _anchored.why = f"anchors could not be worked out ({type(exc).__name__})"
        return None
    if not pts:
        _anchored.why = "the model offered no anchor points"
        return None

    # Anchors are checked against each other before any of them is trusted.
    #
    # One anchor 25s wrong is enough to wreck a song -- wifiskeleton lands at
    # 14.6s on a single bad point, where the same song walked free lands at
    # 0.116s -- and thinning a good song from 32 anchors to 1 changed nothing,
    # so numbers do not protect a walk and sparsity does not endanger it. Only
    # being wrong does.
    #
    # `mine` is where the free walk already put each line. An anchor that moves
    # a line is either correcting real drift, in which case its neighbours are
    # moving the same way, or it is simply misplaced, in which case it is alone.
    # Keep the ones that agree with the crowd; a point that corroborates only
    # itself is not evidence.
    apart = [(line, at, at - mine[line]) for line, at in pts if line in mine]
    middle = statistics.median([d for _l, _a, d in apart]) if apart else 0.0
    if abs(middle) > ANCHOR_SHIFT:
        # The whole set agrees, and agrees on something impossible. When
        # anchors came from a donor this was legitimate -- a stranger timed a
        # different master and the offset had to be absorbed -- but the speech
        # model heard THIS file. There is no clock left to differ by, so a
        # consensus 25s from where the walk heard the words is not a correction
        # to apply, it is the whole set being wrong together. Four such anchors
        # agreed perfectly with each other and cost the song 7.8 seconds.
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
    # Strictly increasing in both, or the segments would overlap and the walk
    # would stop being monotonic -- which is the property being preserved here,
    # not discarded: inside a segment this is the same aligner it always was.
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
    # A segment has to have room for its own characters. Where an anchor would
    # leave less than that -- a donor line landing late, a stretch of text
    # denser than the audio under it -- the anchor is dropped and the two
    # segments either side become one, which is no worse than not anchoring.
    # This song's own pace, in frames per character, as the first pass read it.
    lit = [sp for sp in spans if sp]
    total = sum(len(x) for x in flat) or 1
    pace = ((max(sp[-1].end for sp in lit) - min(sp[0].start for sp in lit))
            / total) if lit else 1.0

    def room(a: int, b: int) -> float:
        """Frames the words from `a` to `b` need before an anchor is doubted."""
        n = sum(len(x) for x in flat[a:b])
        # The hard floor is CTC's own -- a character cannot occupy less than a
        # frame -- and the soft one is this song's pace, allowing for a stretch
        # sung faster than its average.
        return max(n, n * pace * ANCHOR_SQUEEZE)

    ok = [bounds[0]]
    for b in bounds[1:]:
        if b[1] - ok[-1][1] >= room(ok[-1][0], b[0]):
            ok.append(b)
    while len(ok) > 1 and frames - ok[-1][1] < room(ok[-1][0], len(flat)):
        ok.pop()
    ok.append((len(flat), frames))
    if len(ok) < 3:
        # This is the path that saved wifiskeleton: it threw away anchors that
        # left their segments no room, and the free walk that followed came out
        # at 0.116s where three surviving anchors gave 14.628s. It was the only
        # thing working correctly and it had no name.
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
    # Kept on the function so the finished document can carry it. Whether
    # a walk was anchored is the difference between a word 0.1s out and a
    # word 30s out, and it used to be knowable only by watching the log.
    _anchored.last = (len(ok) - 2, len(ok) - 1)
    # WHERE they are, not just how many. Three anchors evenly spread and three
    # bunched in the first verse score the same by count and do entirely
    # different things to a monotonic walk, and the gap between neighbours is
    # what the stretching actually depends on.
    at_line = {n: line for line, n in first.items()}
    _anchored.points = [(at_line.get(n), round(f * per_frame, 2))
                        for n, f in ok[1:-1]]
    return out


def _sounds_like(path: str, words: list[str], decoys: list[list[str]]):
    """How much better this audio matches `words` than songs it is not.

    None if it could not be judged -- the model would not run, or the decoys
    share no vocabulary with the transcript at all, which means a different
    language rather than a different recording.
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
            want = {_flat(w) for w in text}
            want.discard("")
            return len(theirs & want) / max(1, len(want))

        null = statistics.median([met(d) for d in decoys])
        if null < NULL_FLOOR:
            return None
        return met(words) - null
    except Exception:
        return None
    finally:
        release()


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
    # A peak has to stand above its own neighbourhood, not above a constant:
    # a quiet verse and a loud chorus have very different flux.
    pad = ONSET_NEAR
    local = torch.nn.functional.avg_pool1d(
        flux[None, None], kernel_size=2 * pad + 1, stride=1, padding=pad)[0, 0]
    strong = flux > local * ONSET_OVER
    peak = (flux[1:-1] > flux[:-2]) & (flux[1:-1] >= flux[2:]) & strong[1:-1]
    step = ONSET_HOP / rate
    # Walked back down the rise, because the peak of the flux is not the
    # beginning of the sound -- it is the middle of the attack, a few frames
    # after the sound started. Taking the top of the hill as the onset builds
    # that delay into every word that snaps to it, and on a soft-attacked mix
    # the hill is long. So each peak reports the foot of its own rise instead.
    #
    # Capped, so a peak sitting on a long swell reports the top of the swell
    # rather than wherever the flux last happened to dip.
    # Kept so the peak-picking and the snapping can be re-run over a grid of
    # settings without a GPU: everything after this point is arithmetic on
    # these numbers, and an alignment costs minutes on a card shared with
    # whatever else is training.
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
    # What CTC said, before any of this touched it -- the starting point every
    # replayed setting has to begin from. See the note in _onsets.
    # The CTC score rides along because it is the only thing this file knows
    # about a word that might predict whether the word is in the right place.
    # If it does, the wrong ones can be found without a reference and repaired;
    # if it does not, that is worth knowing before anything is built on it.
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
            # Distance from where the sound that made the model fire is
            # expected to be, and a peak after even THAT is doubted: it is
            # more likely the next syllable than this word's beginning.
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
            # No peak stands behind this word, so there is nothing to snap to
            # -- but the model's lateness does not go away just because the
            # onset detector missed. Take the measured amount off, and never
            # past the word before it.
            row["start"] = round(max(floor, row["start"] - ONSET_LATE), 3)
        # The end of the word before follows the start of this one.
        #
        # `floor` is the previous word's START, so the monotonic guard above
        # only stops the two STARTS crossing -- it lets a start move back past
        # where the previous word was said to END, and then two words are lit
        # at once. Measured over 278 songs: CTC alone leaves 6.3% of adjacent
        # words overlapping, and snapping raised that to 35.0%, in every song.
        # Aiming the search earlier is what made it visible; the hole was
        # always there.
        #
        # The end gives way rather than the start, because a start here was
        # measured against a peak in the audio and an end mostly was not --
        # seven ends in ten are simply the next word's start already.
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
    # Which acoustic model reads the audio -- see _w2v() for why there are two.
    #
    # MMS_FA is the one that is always there: it is a forced-alignment bundle
    # and has been in torchaudio for as long as this file has existed, where
    # wav2vec2's ASR bundle is asked for by name and may not answer on an older
    # build. So a missing wav2vec2 costs the choice, not the alignment.
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
    # Downmix before resampling, not after: it is the same answer for half the
    # arithmetic, and on a four-minute stereo stem that is a real second.
    wave = _resample(_channels(wave, 1), rate, bundle.sample_rate)

    # The lead's words are the walk. Ad-libs are a second voice singing at the
    # same time, so they are held back here and timed against the same frames
    # afterwards -- see _asides. Without `where` there is nothing marking them
    # and this is the single stream it always was.
    # `is not None`, not truthiness: the first ad-lib group on a line is
    # numbered 0, and a plain `if w[3]` puts it back in the lead's stream.
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
            # An ASR head answers in logits; MMS_FA answers in log
            # probabilities and needs no wrapping.
            return _emission(_logits(moved) if w2v else moved, wave, dev, win,
                             log, stop=stop)
        finally:
            # Straight back to the CPU: the emission is the answer and the
            # weights are a gigabyte in the way of whatever runs next.
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
    # Alignment itself stays on the CPU. It is a walk over a frames-by-tokens
    # grid rather than a matrix multiply, it takes about a second on a song, and
    # keeping it here means the peak that mattered was the emission above.
    spans = aligner(emission, tokenizer(flat))
    # The first pass is also the calibration for the second: see _anchored.
    # The emission is not recomputed for it -- that is the expensive half, and
    # the walk over it is about a second on a song.
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
        # The span the aligner returns is per TOKEN, and a token here is one
        # CHARACTER of the flattened word -- so the middle of that list, which
        # this used to drop on the floor, is sub-word timing that has been
        # free all along. Stage three cuts words up with it.
        #
        # Only kept where the two lists line up. The tokenizer is free to fold
        # a character away, and a mismatched list would put a syllable
        # boundary on the wrong letter without ever looking wrong.
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
        # MAX_WORD is to_document's other floor, and a long line under one
        # short ad-lib would sail straight past it.
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
            # A line with no lead to sing under -- nothing places it, and a
            # guess would be a guess about which part of the song it is in.
            continue
        f0, f1 = bounds
        # Reaching past the line's end, which is the whole fix -- see the note
        # on ADLIB_REACH. The lead's own span decides where to START looking;
        # it has no business deciding where to stop.
        f1 = min(emission.shape[0], f1 + max(1, int(ADLIB_REACH / per_frame)))
        flat = [(n, _flat(words[n])) for n in idx]
        flat = [(n, f) for n, f in flat if f]
        if not flat:
            continue
        # An ad-lib cannot be given fewer frames than it has characters, so a
        # short line under a long ad-lib is CTC asking for the impossible. Not
        # a reason to drop the words: they are sung, and a "(Woah)" that cannot
        # be walked is still a "(Woah)" the page has to show. Share the line's
        # own frames out between them instead -- the same last resort
        # _share_gaps applies to whole lines, for the same reason.
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
# stage three: dividing the words, for English
#
# The spans above are per character, so cutting a word into syllables at its
# own letters costs nothing and was demonstrated before any of this was
# written. The cuts come out acoustically good -- "another" divides at the
# same two places on both occurrences in a line -- and linguistically wrong in
# four ways that no rule over letters can fix, because English spelling does
# not say how many syllables a word has:
#
#     hope      ends in a letter nobody sings, and got a 20ms syllable
#     dumbed    ends in -ed that is one consonant, and got a syllable for it
#     packaged  ends in -ed that genuinely is a syllable, spelt the same way
#     around    came out ar-ound, since a letter rule cannot move the r on
#
# A pronunciation says all four outright, because there are no silent letters
# in one: count the vowels and that is the number of syllables. So the number
# of pieces and where the word divides come from espeak, and only the letters
# shown on screen come from the spelling.
#
# This is additive twice over, and both halves matter.
#
# MMS_FA still places the WORDS. That is the alignment measured at a median of
# +0.12s with 67 of 69 lines inside a quarter second, and it is not being
# replaced by a model nobody here has scored -- every word keeps the start and
# the end it already had, and this only divides the inside of it.
#
# And English is the only language that comes down here at all. espeak's
# phoneme sets are per language, while MMS_FA is multilingual precisely
# because it reads romanised text in 29 symbols -- which is what makes the
# Japanese, Korean and Chinese songs work, and what would be thrown away by
# making the phoneme path the general one. _english() has to be sure, and on
# anything it is not sure about the words stay whole exactly as before.
#
# Three tiers, each falling back to the one below it:
#
#   1. no phonemizer        words stay whole -- what this file did before
#   2. phonemizer           the count and the cut are right, and the boundary
#                           TIMES come from MMS_FA's own character spans
#   3. + the phoneme model  the boundary times are measured against a model
#                           whose vocabulary is phonemes instead of letters
#
# Tier 2 is what fixes the four words above, and it costs one G2P call for the
# song -- the whole of the linguistic argument is settled before any audio is
# involved. Tier 3 is a second 1.2 GB CTC model and a second pass over the
# song, and it buys one thing: where the boundary falls in the audio. Tier 2
# has to ask a letter model when a LETTER was sung and use that as the edge of
# a sound; tier 3 asks a model that was trained on the sounds themselves. The
# cut is in the same place on the page either way.
# --------------------------------------------------------------------------
PHONE_MODEL = "facebook/wav2vec2-lv-60-espeak-cv-ft"

# What tier 3 costs on the card, measured the same way and on the same machine
# as the two above:
#
#     wav2vec2-lv-60-espeak-cv-ft   8.0s window  1.81 GB   30.0s  3.36 GB
#
# Which is MMS_FA's figure to the hundredth, twice over, and worth writing
# down because it looks like a coincidence and is not: both are wav2vec2-large
# and what costs is the emission, not the head. 392 output symbols against 29
# is four frames' worth of floats on a song and disappears into the rounding.
#
# So this is ALIGN_COST, and the margin is the same quarter over the
# measurement. It is kept as its own name rather than aliased because the two
# are equal by measurement rather than by construction, and a different model
# here would move one and not the other.
PHONE_COST = (1.6, 0.08)
PHONE_WINDOW = (8.0, 30.0)

# Every vowel espeak writes, and the marks it hangs off them. A run of these
# inside a phone is a nucleus and a nucleus is a syllable -- the same rule the
# character version applied to letters, where it is a guess, and here it is
# simply what the notation means. Syllabic consonants come through carrying
# their own schwa ("little" is l ɪ ɾ əl), so they need nothing special.
# ᵻ and ᵿ are espeak's own, for the reduced vowels English writes with i and u
# and does not really say -- the second vowel of "addicted" is one, and leaving
# them out cost that word a syllable.
IPA_VOWEL = frozenset("iɪyʏeøɛœæaɶɑɒɔoʊuʉɯɤʌɐəɚɜɝɞɵɘɨᵻᵿ" "ːˑ̩̈")
# Two vowels next to each other are two syllables -- "chaos" is k eɪ ɑː s --
# unless espeak split a diphthong it usually writes as one phone.
DIPHTHONG = frozenset({"aɪ", "aʊ", "eɪ", "oʊ", "ɔɪ", "əʊ", "ɪə", "eə", "ʊə",
                       "ɛə", "ɔə", "ɑɪ", "ɑʊ"})
# What an English word is allowed to begin with, in LETTERS rather than
# sounds, since this decides where the spelling divides and not where the
# sound does. Any single consonant, plus these.
ONSET = frozenset("""bl br ch cl cr dr dw fl fr gl gn gr kl kn kr ph pl pr ps
pn qu rh sc sh sk sl sm sn sp st sw th tr tw wh wr chr phr sch scl scr shr spl
spr squ str thr""".split())
VOWEL_LETTER = frozenset("aeiouy")
# Two letters for one sound. Maximal onset may hand the whole of one to the
# next syllable or leave the whole of it behind, and must never cut it in
# half: an-oth-er, never a-not-her.
DIGRAPH = frozenset({"th", "sh", "ch", "ph", "wh", "gh", "ng", "qu", "zh"})
# The vowels English will not end a syllable on -- the "checked" ones, which
# have to be closed by a consonant. This is the correction that stops maximal
# onset from running away with itself, and it is the clearest thing the
# phonemes buy that letters could not have said:
#
#     around    ɐ    free, so the r goes forward       a-round
#     distant   ɪ    checked, so the s stays behind    dis-tant
#     living    ɪ    checked, and there is only a v    liv-ing
#     another   ɐ ʌ  one of each                       a-noth-er
#
# Without it "distant" came out Di-stant and "pistol" pi-stol, because st is
# a perfectly legal thing for a word to begin with and nothing else was
# arguing. A long vowel or a diphthong is free and keeps the plain rule.
CHECKED = frozenset({"ɪ", "ɛ", "æ", "ʌ", "ʊ", "ɒ", "ᵻ", "ᵿ", "e"})

# Words a song in English is very unlikely to do without. The test is not "is
# this the Latin alphabet": Spanish, German, Dutch and Indonesian all pass
# that, and espeak asked for en-us would read them aloud in English --
# confidently, and as nonsense. It is not the alphabet that has to be
# recognised, it is the language.
ENGLISH = frozenset("""a all am an and are as at be been but by can can't come
did do don't down for from get go going got had has have he her here him his
how i i'll i'm if in is it it's just know let like little love make me my never
no not now of oh on one only or our out over said say see she should so some
take tell than that the their them then there they this time to too up us very
was we well were what when where which who why will with would you your
you're yeah""".split())
# How many of a document's words have to be on that list. English lyrics run
# well above this; the point of the floor is the languages that share the
# alphabet and score a handful of coincidences ("in", "so", "was" are German
# words too), not the ones that share nothing.
ENGLISH_SHARE = 0.12
# Enough words to ask the question of at all. A four-line fragment can hit any
# share by accident.
ENGLISH_MIN = 25

_g2p = None
# Pronunciations, memoised the way _reading is and for the same reason: this
# is asked once per distinct word and a song repeats itself heavily.
# Bounded for the same reason _reading is cleared: a window left open for a
# week would otherwise accumulate every word of every English song it saw.
# Cleared wholesale rather than evicted one at a time -- this is a pure
# function of the word, so the only cost of forgetting is asking espeak again.
SPOKEN_MAX = 20000
_spoken: dict[str, list[str]] = {}
_phone_built: tuple | None = None


def _english(words: list[str]) -> bool:
    """Is this document in English, surely enough to pronounce it as English?"""
    # An unspaced script is decided before the word list is even looked at.
    # _flat romanises those, so a Japanese document arrives here as plausible
    # Latin text and only the vocabulary test would be standing between it and
    # an English pronunciation of romaji.
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
    # False is "there is no espeak on this machine", whoever set it -- the
    # cache below is per language, and that answer is not.
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
        # espeak's own spelling of a language is not always the obvious one:
        # French is "fr-fr" and plain "fr" is not a voice it has, so asking for
        # it failed silently and the words stayed whole. Try what was asked,
        # then the doubled form, then the bare prefix.
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
                    # Older phonemizer, fewer knobs. The defaults are the same
                    # answer for text already in the language asked for.
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
    # Keyed by LANGUAGE and word, not by word. "hermosa" is a different sound
    # in Spanish and in English, and a cache that cannot tell them apart hands
    # back whichever was asked for first -- which was invisible while this only
    # ever spoke English and is a wrong answer the moment it does not.
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
        # Asked and answered: remember the silence too, or every song retries
        # a backend that is not going to start.
        for w in want:
            _spoken[(lang, w)] = []
        return
    for w, said in zip(want, got):
        # espeak reads some tokens as several words -- "1999" comes back as
        # nineteen|ninety|nine -- and for this purpose it is all one word's
        # worth of sound.
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
                continue          # the back half of one vowel, not a new one
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
        # A leading y is a consonant ("you"), anywhere else it is a vowel
        # ("rhythm", "very"). It is the only letter that has to be asked.
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
# where a written word divides, from a dictionary rather than from rules
#
# _cut_letters below works out where English spelling divides, from the letters
# up: vowel runs, maximal onset, doubled consonants, digraphs that may not be
# halved, checked vowels that need a coda. It is careful and it is documented
# and it is still a set of rules approximating a thing that is really a
# per-word fact -- it says "beau-tif-ul" where a dictionary says "beau-ti-ful".
# And it is English: applied to French it would be confidently wrong, which is
# why divide() would only ever run on English.
#
# pyphen is those facts, as hyphenation dictionaries, for 85 languages. It is
# what an old version of this program used, and asking it is a lookup rather
# than an argument.
#
# It does not replace the phonemes. The pronunciation still says HOW MANY
# pieces a word has and where they fall in the audio; this only says where the
# spelling divides to match. Where the two disagree about the count, the rules
# below are used instead -- a dictionary that wants three pieces where the
# sounds say two cannot be laid over the audio at all.
# --------------------------------------------------------------------------
_hyphen: dict = {}


def _speller(lang: str):
    """pyphen for `lang`, or None. Cached per language, built on first ask."""
    if lang in _hyphen:
        return _hyphen[lang]
    got = None
    try:
        import pyphen
        # espeak's names are not pyphen's: en-us against en_US, and pyphen has
        # some languages only as a bare code. Try the exact name, then the
        # language without its region.
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
    # Too many candidates: merge the neighbours with the least between them,
    # rightmost first. A final silent e is separated from the vowel before it
    # by one consonant at most, so it is the first to go.
    while len(runs) > want:
        gaps = [(runs[k + 1][0] - runs[k][1] - 1, k) for k in range(len(runs) - 1)]
        _, k = min(gaps, key=lambda g: (g[0], -g[1]))
        runs = runs[:k] + [(runs[k][0], runs[k + 1][1])] + runs[k + 2:]
    cuts = [0]
    for k in range(1, len(runs)):
        lo, hi = runs[k - 1][1] + 1, runs[k][0]
        cluster = flat[lo:hi]
        # A doubled consonant is two letters for one sound, and English has
        # always divided between them -- lit-tle, run-ning. ck is the same
        # thing spelt differently, so pack-aged rather than pac-kaged. This
        # is asked before maximal onset because it beats it: "tl" is not
        # something a word may begin with, so the onset rule alone would have
        # handed over only the l and written litt-le.
        # ck differs from tt in where the cut goes, not whether: a doubled
        # letter divides between its halves (lit-tle) and ck is a digraph that
        # is never split, so the whole of it stays behind (pack-aged).
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
        # The syllable ending here may not be able to end on its vowel. Leave
        # it a consonant -- but a digraph cannot be halved to find one, so
        # where the only letter available is the back of a th or a ng, the
        # whole cluster stays behind instead: a-noth-er, not a-not-her.
        # A merged candidate has swallowed the consonant between its two
        # halves -- "some" is one piece here, and the m inside it is already
        # the coda a checked vowel needs. Without asking, "something" divided
        # someth-ing, having gone looking for a coda it had all along.
        closed = any(c not in VOWEL_LETTER
                     for c in flat[runs[k - 1][0]:runs[k - 1][1] + 1])
        if opened is not None and not opened[k - 1] and take and not closed:
            short = min(take, len(cluster) - 1)
            at = len(cluster) - short
            if short and cluster[at - 1:at + 1] in DIGRAPH:
                short = 0
            take = short
        cuts.append(hi - take)
    # A piece with no letters in it cannot be shown or timed. This should not
    # happen -- every piece keeps its own vowel -- but a cut list that is not
    # strictly increasing would put a zero-width syllable on screen.
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
        return None                       # romanised, or folded: not ours to cut
    # The dictionary first, the rules where it has nothing to say. Same shape
    # of answer either way: the index each piece starts at.
    cuts = (_dict_cuts(flat, len(syl), lang)
            or _cut_letters(flat, len(syl), _open(phones, syl)))
    if len(cuts) < 2:
        return None
    start, end = float(row["start"]), float(row["end"])
    # A word has to be long enough to hold the pieces it is about to be cut
    # into. Nothing stops the aligner returning a 30ms word, and three
    # syllables inside one of those would have to run backwards to fit --
    # a syllable that ends before it starts is worse than an undivided word.
    if end - start < MIN_SYL * len(syl):
        return None
    chars = row.get("chars")
    at: list[float] = []
    if spans and len(cuts) == len(syl):
        # The measured edge of the first phone of each syllable after the
        # first. Only when the letters could supply exactly as many pieces as
        # the sounds asked for -- with any other count there is no saying
        # which boundary is which, and the characters below are the safer
        # answer than a guess dressed up as a measurement.
        at = [float(spans[syl[k][0]][0]) for k in range(1, len(syl))]
    elif chars and len(chars) == len(flat):
        at = [float(chars[c][0]) for c in cuts[1:]]
    if len(at) != len(cuts) - 1:
        return None
    # Word edges are MMS_FA's and stay MMS_FA's. Everything inside is pushed
    # into the interval it measured, in order, leaving each piece the 20ms
    # _fill treats as the narrowest a syllable may be -- so a phoneme pass
    # that has wandered off cannot move a word, only divide it badly, and a
    # bad division costs one word rather than the line it sits in.
    #
    # Nothing else is imposed. An honestly short first syllable is common in
    # exactly the words this was built for -- the schwa of "a-round" is a
    # fraction of the rest of it -- so a measurement is only overruled when
    # keeping it would put the pieces out of order.
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
    # The invariant the frontend holds itself to as well: the pieces have to
    # rebuild the word exactly, or the line on screen is no longer the line
    # that was in the document.
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
                i += 1                    # a mark this model does not carry
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
    # Cleared per song: last song's disagreements on this song's document
    # would be worse than none.
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
        # Back from the model's symbols to espeak's phones: one phone can have
        # taken more than one symbol, so a phone runs from the start of its
        # first to the end of its last.
        per, k = [], at
        for phone in said[n]:
            width = len(_ids(vocab, [phone]))
            if not width:
                per.append(None)
                continue
            per.append((spans[k].start * per_frame + offset,
                        spans[k + width - 1].end * per_frame + offset))
            k += width
        # A phone the vocabulary did not carry borrows the edge beside it,
        # so the list stays one entry per phone and _pieces can index it.
        for i, item in enumerate(per):
            if item is None:
                near = next((p for p in per[i + 1:] if p), None) or \
                       next((p for p in reversed(per[:i]) if p), None)
                per[i] = near or (0.0, 0.0)
        # The guard against a phoneme pass that has drifted off the words:
        # if what it says about this word does not overlap where MMS_FA put
        # the word, none of its boundaries inside that word mean anything.
        row = rows[n]
        lo, hi = per[0][0], per[-1][1]
        share = min(hi, row["end"]) - max(lo, row["start"])
        if share <= 0.5 * min(hi - lo, row["end"] - row["start"]):
            # A SECOND OPINION, not just a reject. Two models read this word:
            # the character head, which matches letters, and the phoneme head,
            # which matches sounds. Where they disagree this violently is
            # where the letters and the sound part company -- a reduced vowel,
            # a word run into the next one, a syllable held past its spelling.
            # Thrown away silently until now; kept so it can be looked at.
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
        # A tuple, an object with .logits, or a mapping that indexes like
        # both -- transformers has answered in all three shapes across its
        # versions, and the first field is the logits in every one of them.
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
    # Which language to pronounce this in, and whether to at all.
    #
    # Asked for explicitly, or English by detection, and nothing else -- which
    # is a smaller promise than "espeak speaks a hundred languages" and is the
    # honest one. espeak gives PHONEMES for all hundred, and the phonemes are
    # not the hard part: _pieces() has to lay the syllables it finds back over
    # the WRITTEN word, because the written word is what is on screen, and the
    # rules it uses to do that -- ONSET, DIGRAPH, the checked vowels -- are
    # English spelling. They are close to right for a transparent orthography
    # (Spanish, Italian) and wrong for French, and this file has no way to know
    # which it is being handed.
    #
    # So: `lang` is a switch for somebody who knows what their song is and can
    # look at the result, not a detector. Left alone, nothing changes.
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
            # Tier 3 is the half that can fail on somebody else's model
            # download, and tier 2 is a complete answer without it. Say so
            # and carry on rather than losing the syllables altogether.
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
# the whole of it
# --------------------------------------------------------------------------
# Set by heard()/_anchored() during a run and read when the document is
# built: how many lines the walk was pinned on, or why it was not.
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
    # Cleared, not left over: these ride on the document, and last song's
    # count on this song's answer is worse than no count at all.
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
    # Cleared per run: these are read when the document is built, and a stale
    # value from the previous song would claim anchors this one never had.
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

    # Says nothing at all unless --debug asked for it, so the ordinary run
    # keeps the four lines it has always printed.
    #
    # Takes a CALLABLE, not a string. Passing the message directly builds it
    # whether or not anyone will read it -- which is waste on every ordinary
    # run, and was a crash on one: a debug line asking a tensor its
    # element_size() ran against a test double that had no such method, and
    # took the whole alignment down through a path that is supposed to be off.
    def step(make) -> None:
        if debug:
            _say(log, make() if callable(make) else make)

    try:
        _stop(stop)
        step("stage 1/5  reading the audio")
        wave, rate = _read(audio_path)
        step(lambda: f"  {wave.shape[0]}ch x {wave.shape[1]} samples at "
                     f"{rate} Hz ({wave.shape[1] / rate:.0f}s)")
        # How much of this copy is silence the track does not have. Worked out
        # on the mix, before separation, and applied to every time measured
        # below -- see lead_in(). Only when the copy is actually longer than the
        # track: silence at the head of a copy that is the RIGHT length is the
        # master's own, and subtracting it would put every line early.
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
        # Kept before demucs touches it, for `emit_from="mix"`.
        #
        # Separation is not free of consequence for the acoustic model: demucs
        # is a mask over a spectrogram, and what it leaves behind on a loud
        # mix is a vocal with holes and smeared transients where the mask was
        # wrong. wav2vec2 was trained on neither -- it read clean speech. So
        # "the stem is easier to hear" and "the stem is a distribution the
        # model has never seen" are both true, and which one wins is a
        # question about this library, not a thing to reason out. This lets
        # the emission be taken from the untouched mix while everything that
        # genuinely needs a separated vocal -- the VAD, the onsets, the
        # syllable split -- still gets one.
        mix, mix_rate = (wave.clone(), rate) if emit_from == "mix" else (None, 0)
        if stems:
            dev, win, why = room(want, DEMUCS_COST, DEMUCS_WINDOW, spare)
            _say(log, f"  {why}")
            if dev != "cpu":
                _cap(spare)
            wave, rate = separate(wave, rate, dev, win, name, log, stop)
            # Built here, from the stem, before anything downsamples it. Silero
            # first -- it answers "is this a word" where the envelope answers
            # "is this loud", and a vocal stem is full of loud things that are
            # not words. The envelope stays as the fallback for a machine
            # without it.
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
            # The full mix is loud all the way through, so its energy says
            # nothing about whether a voice is still there.
            voice = None
        step("stage 3/5  hearing where the lines fall")
        dev, win, why = room(want, ALIGN_COST, ALIGN_WINDOW, spare)
        _say(log, f"  {why}")
        if dev != "cpu":
            _cap(spare)
        _stop(stop)
        # Where the lines start, heard from this very audio, used only to pin
        # the walk -- never for a word of its text. `mine` is what the first
        # pass measured and is not wanted: the donor this replaced needed it to
        # work out the constant between two clocks, and there is only one clock
        # here. Without anchors this is the single monotonic pass it always was.
        pin, spoken, heard_lines = None, None, None
        if anchors:
            # How much audio the card can hold at once, not how long the song
            # is: the decode is chunked, so a six-minute track costs whatever
            # one chunk costs. room() sizes the chunk to what is free.
            adev, achunk, awhy = room(want, ASR_COST, ASR_WINDOW, spare)
            _say(log, f"  {awhy}")
            if adev != "cpu":
                _cap(spare)
            # Supplied from outside, or heard here. The parameter exists so a
            # different speech model can be compared on equal terms: everything
            # downstream is identical and only the anchors differ, which is the
            # only way to tell an aligner apart from the pipeline around it.
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
            # The anchors are gone -- they never won a timing -- but the speech
            # model is still the only thing here that listens to the audio
            # without being told what it should say. Kept as a WITNESS.
            #
            # It is the only check that can catch the wrong recording. Every
            # timing statistic conflates "bad anchors on the right song" with
            # "the right anchors on the wrong song": Papa Roach's anchors sat
            # +61s out and the song was fine, while Labyrinth's audio was not
            # this song at all and every per-word score cleared the floor,
            # because CTC will confidently place something anywhere.
            #
            # Whether the words match is a different question from where they
            # are, and only this can answer it.
            adev, achunk, awhy = room(want, ASR_COST, ASR_WINDOW, spare)
            if adev != "cpu":
                _cap(spare)
            # The separation is finished and its stem is in memory, but the
            # model that made it is still on the card. Nothing below needs it,
            # and holding it means the check that catches a wrong recording is
            # the first thing to be squeezed out -- on a desktop with a player
            # running, that was every time.
            release()
            heard.why = ""
            # A smaller model on purpose. Anchoring needed accurate word
            # timestamps; this only needs to know WHICH words are in the audio,
            # and the small model's 1.9 GB is the difference between the check
            # running and not running on a card that also has a player, a
            # browser and a desktop on it.
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
                    # Words that mean something. Any two English lyrics share
                    # "the", "you", "and", so counting them measures English
                    # rather than this song -- wordle freestyle scored 46%
                    # against a floor of 42%, and almost all of both was
                    # furniture.
                    want = {_flat(w) for w in text} - COMMON
                    want.discard("")
                    return len(theirs & want) / max(1, len(want))

                share = met(words)
                align.overlap = round(share, 3)
                # Against a null, not against a threshold.
                #
                # "How much of the lyric did it hear" measures how well the
                # speech model hears THIS GENRE, which is the confound: a
                # correct lo-fi recording scored 42% and a wrong one 34%. But
                # unrelated lyrics share function words with any transcript, so
                # the same question asked of songs this is definitely NOT gives
                # the floor for this recording and this model. A correct song
                # sits far above its own floor; a wrong one sits on it. When the
                # model hears the genre badly both fall together and the margin
                # survives.
                if decoys:
                    null = statistics.median([met(d) for d in decoys])
                    if null < NULL_FLOOR:
                        # The floor is the point. Unrelated English lyrics share
                        # function words with any English transcript, so a null
                        # near zero means the transcript and the decoys have no
                        # common vocabulary to share -- a different language or
                        # script, not a verdict about this recording. Two
                        # Japanese songs were flagged as wrong recordings this
                        # way, on nulls of exactly 0%.
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
        # Which model reads the audio, when the caller has not insisted.
        #
        # wav2vec2 is an ENGLISH ASR head and MMS_FA is multilingual, so the
        # choice is really about what the words are: wav2vec2 sounded better on
        # an English track, and it has nothing to say about a Japanese one that
        # MMS_FA romanises and reads. The same test the syllable stage already
        # uses decides it, so a document is judged once and both stages agree.
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
            # On by default since it was measured: 6 songs better, 2 unchanged,
            # 0 worse, against a noise floor of exactly zero -- and better by
            # ear on the songs that have no reference to measure against.
            #
            # It is the only stage that sees a spectrogram. wav2vec2 reads the
            # waveform directly, so where a sound BEGINS is not something it
            # was ever told; spectral flux is information the aligner does not
            # otherwise have, rather than a second opinion on what it has.
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
            # Stage three is decoration on a finished answer, so it is inside
            # the try but must not be able to spend it: anything at all going
            # wrong here leaves `got` exactly as the aligner returned it.
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
        # Asked for, so not an error and not worth a traceback. The caller
        # knows it stopped this; align.stopped is for anyone downstream who
        # has only the None to go on.
        align.stopped = True
        align.last_error = "stopped"
        return None
    except Exception as exc:
        import traceback
        align.last_error = f"{type(exc).__name__}: {exc}"
        align.last_trace = traceback.format_exc().strip().splitlines()[-6:]
        return None
    # Hand back what the card is holding but no longer using. Every stage moves
    # its weights off the card when it finishes, and the allocator keeps the
    # freed blocks anyway -- so a player that has aligned one song sits on
    # gigabytes of reserve it will not touch again until the next one. Measured
    # on the running player: 4.1 GB held, which left 2.0 GB free and sent every
    # stage of the next run to the CPU for want of room that was already ours.
    torch = _torch()
    if torch is not None:
        with contextlib.suppress(Exception):
            torch.cuda.empty_cache()
    placed = len(got.get("words") or [])
    _say(log, f"  {placed} of {len(words)} words placed")
    out = to_document(doc, words, where, got, voice, spoken)
    if out is None:
        # Distinct from every failure above: the models ran and answered, and
        # nothing they said survived MIN_SCORE and MAX_WORD. Saying so beats
        # the bare None that used to make this look like a network fault.
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
# getting the audio in the first place
#
# Spotify's stream is not a file this program can open, so a copy has to come
# from somewhere else for the few minutes the alignment takes. Fetched to a
# temporary file, converted to what demucs wants, and deleted -- see `fetched()`,
# which does the deleting whether the alignment worked or not.
#
# The duration check is the part that matters technically. A search will happily
# return a live take, a remix, a sped-up upload or an hour-long compilation, and
# an alignment against the wrong recording does not fail -- it returns confident
# timings for a performance nobody is listening to. Anything that is not the
# same length as the track being played is refused.
# --------------------------------------------------------------------------
# How far a copy's length may sit from the track's before it is a different
# recording. Wide enough for a trailing silence or a faded outro, far short of
# an extended mix.
LENGTH_TOL = 3.0


# How many acceptable copies to try downloading before giving up.
#
# More than one because being findable and being fetchable are different
# questions, and the second one is answered by somebody else's server. Of the
# four uploads of one track that all matched its length exactly, the one this
# picked answered 403 to every request while the artist's own copy of the same
# recording downloaded in a second. Trying one and reporting failure meant a
# song that could plainly be aligned simply was not.
FETCH_TRIES = 3
# A pinned copy is worth insisting on: giving up on it silently swaps the
# recording, which moves a song's measured error by tens of seconds.
PIN_TRIES = 3


def find(query: str, length: float, tries: int = 8,
         artist: str = "") -> list[tuple[str, float]]:
    """Every search hit whose length matches the track, closest first.

    Metadata only -- nothing is downloaded until something has been chosen.

    A list rather than the single best, because the best one may not be
    downloadable and the next is usually the same recording: uploads that agree
    on the length to within a second or two have, in practice, agreed about
    which recording they are.

    What was rejected is left on `find.near` -- the closest hit that missed the
    tolerance -- so a caller can say "wanted 300s, the closest was 295s"
    instead of leaving the user to go and look at YouTube themselves.
    """
    find.near, find.seen = None, 0
    # More than one way of asking, because one is demonstrably not enough.
    #
    # "ToxiPlays i wish it was me (after all)" returns the official video
    # (212s), a live take (224s) and a remix (163s), and never the album track
    # at 202s -- not in the first eight results, and not in twenty either, so
    # searching deeper does not reach it. The same query with "audio" on the
    # end returns it first. Which shape works is a fact about YouTube's ranking
    # rather than about the song, so all of them are asked and the results are
    # pooled; the length test below decides between them as it always did.
    seen_urls: set[str] = set()
    rows: list[str] = []
    asks = [query, f"{query} audio"]
    bare = query.split(" ", 1)[1] if " " in query else ""
    if bare:
        asks.append(bare)
    # ALL AT ONCE, AND WITHOUT EXTRACTING EACH VIDEO. Two separate costs were
    # being paid here, and neither bought anything:
    #
    #   * yt-dlp was asked for full metadata on every hit, which makes it visit
    #     each video in turn. Measured on one search: 10.3s against 1.1s with
    #     --flat-playlist, for the same eight results. Everything this function
    #     reads -- duration, webpage_url, uploader -- is in the flat answer;
    #     nothing else was ever looked at.
    #   * the three phrasings were asked one after another, so the whole thing
    #     cost the sum of them.
    #
    # Together: 31.6s to choose a copy, before a byte of audio is fetched.
    def ask_for(ask: str) -> list[str]:
        cmd = ["yt-dlp", f"ytsearch{tries}:{ask}", "--dump-json",
               "--no-warnings", "--skip-download", "--no-playlist",
               "--flat-playlist"]
        try:
            got = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=120)
        except Exception:
            return []
        return got.stdout.splitlines()

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(asks)) as pool:
        for got in pool.map(ask_for, asks):
            rows.extend(got)
    # Closest length first, not search order. Search order has nothing to do
    # with which upload is the right recording, and a live take three seconds
    # under can easily be listed above the album cut that matches exactly --
    # taking the first acceptable hit picked the live one.
    keep, near = [], None
    for row in rows:
        try:
            hit = json.loads(row)
        except json.JSONDecodeError:
            # yt-dlp writes one object per line and a progress note now and
            # then. A line that is not JSON is not an error worth hearing
            # about -- anything else raising here would be our own bug.
            continue
        dur = float(hit.get("duration") or 0)
        url = hit.get("webpage_url")
        if not dur or not url:
            continue
        if url in seen_urls:      # the same upload from two of the searches
            continue
        seen_urls.add(url)
        find.seen += 1
        gap = abs(dur - length) if length else 0.0
        if length and gap > LENGTH_TOL:
            if near is None or gap < near[0]:
                near = (gap, dur, str(hit.get("title") or "")[:60])
            continue
        keep.append((gap, url, dur, str(hit.get("uploader") or "")))
    # Length alone cannot choose between uploads of the same song, and asking
    # it to was a real fault: "Illegal" had FOUR copies at +0.33s, the sort put
    # them in whatever order the searches happened to return, and one of them
    # is an edit whose vocals begin nine seconds later than the album's. The
    # song scored 0.08s against a reference on one run and 8.98s on the next,
    # with nothing in this program changed between them.
    #
    # So: near-ties are grouped, and inside a group the artist's own upload
    # wins. An official channel is far likelier to be the master than a
    # re-upload, and "who put this here" is metadata the search already
    # returned and this used to throw away. Failing that the URL decides --
    # arbitrary, but the same arbitrary answer every time, which is the part
    # that was actually missing.
    who = GR.key(_bare(artist)) if artist else ""

    def rank(k):
        gap, url, _dur, uploader = k
        theirs = GR.key(_bare(uploader))
        mine = 1
        if who and theirs:
            # "- Topic" channels are YouTube's own auto-uploads of the release.
            mine = 0 if (who in theirs or theirs in who) else 1
        return (round(gap, 1), mine, gap, url)

    keep.sort(key=rank)
    keep = [(g, u, d) for g, u, d, _w in keep]
    if near:
        find.near = (near[1], near[2])
    return [(url, dur) for _gap, url, dur in keep]


find.near: tuple | None = None
find.seen = 0


# Copies fetched for alignment, in the project rather than the cache so
# they are visible and removable without hunting through ~/.cache.
AUDIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "fetched"
# What the kept copies may take up. Old ones go first, and "old" is when they
# were last USED, not fetched: the songs played often are the ones worth having.
AUDIO_CAP_GB = 8.0
# Tried in order. Measured 2026-08-14: default 403s, web_safari has no audio
# format, these two both download. Worth re-checking when fetches start
# failing again -- YouTube changes which clients it will serve. Leaving the
# default IN the list is not harmless: yt-dlp then picks its format (251) and
# 403s on it, so the working clients never get asked.
YT_CLIENTS = ("tv_simply", "android_vr")
# How many times a download is retried before the copy is given up on, and
# how long to wait between (multiplied by the attempt number).
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


def fetch(url: str, path: str) -> str | None:
    """Audio from `url` as 44.1kHz stereo wav at `path`, or None.

    Full rate and both channels, unlike the mono 16kHz this used to fetch: the
    separation runs first now and it wants the mix as it was mastered. The
    aligner's own downmix happens in memory afterwards, so nothing is lost by
    handing it the better copy.

    Why it failed is left on `fetch.last_error`. It used to be thrown away, and
    a 403 on one upload then reached the user as "no copy at the right length"
    -- which sent them to check the one thing that was not wrong.
    """
    fetch.last_error = ""
    base = ["yt-dlp", url, "-f", "bestaudio/best", "--no-playlist",
            "--no-warnings", "--quiet", "-x", "--audio-format", "wav",
            "--postprocessor-args", f"ffmpeg:-ac 2 -ar {SEP_RATE}",
            "-o", path.rsplit(".", 1)[0] + ".%(ext)s"]
    # Which client yt-dlp claims to be, and WHY this is now a fallback rather
    # than the first thing tried.
    #
    # These two clients were pinned because the default was getting "403:
    # Forbidden" on the media URL -- half of one evening's fetches. That was
    # true of the yt-dlp of the day. It is now the other way round: on
    # 2026.08.19 the default clients serve and `android_vr` is the one that
    # 403s, so the workaround had become the fault. Six songs of a nine-song
    # benchmark could not be fetched because of it, which read as YouTube
    # blocking us and was our own flag.
    #
    # So: default first, these second. Whichever way the far end turns next,
    # one of the two is likely to work, and neither is baked in as the truth.
    cmd = list(base)
    # Retried, because the far end is unreliable rather than unwilling. The
    # SAME command against the SAME video fails about half the time with a 403
    # and succeeds on the next attempt seconds later. Without this the failure
    # does not look like a failed download: the pinned copy is abandoned, the
    # search runs again, and a different recording is aligned and pinned in its
    # place. That cost three songs their copies in one evening, one of them
    # ending up twenty times worse, and it looked like the aligner regressing.
    try:
        for attempt in range(FETCH_RETRIES):
            # Half the attempts as yt-dlp sees fit, half as the pinned clients.
            cmd = list(base) if attempt < FETCH_RETRIES // 2 else list(base) + [
                "--extractor-args",
                "youtube:player_client=" + ",".join(YT_CLIENTS)]
            try:
                subprocess.run(cmd, capture_output=True, timeout=600, check=True)
                break
            except subprocess.CalledProcessError as again:
                said = (again.stderr or b"").decode("utf-8", "replace")
                if attempt + 1 < FETCH_RETRIES and any(
                        x in said for x in ("403", "429", "Forbidden",
                                            "Too Many Requests", "timed out",
                                            "not available", "reloaded")):
                    time.sleep(RETRY_WAIT * (attempt + 1))
                    continue
                raise
    except subprocess.CalledProcessError as exc:
        said = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        # yt-dlp puts the useful line last and a stack of context above it.
        fetch.last_error = (said[-1].replace("ERROR: ", "") if said
                            else f"yt-dlp exited {exc.returncode}")
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
            decoys: list[list[str]] | None = None):
    """A copy of the song for as long as the `with` block runs, and not a moment
    longer. Yields a path, or None if no copy could be had.

    Why not, in the caller's words, is on `fetched.last_error`. There are three
    quite different answers -- the search found nothing, it found nothing of
    the right length, or it found copies and none of them would download -- and
    they had all been reported as the middle one.

    The delete is in a finally: an alignment that raises, times out or is
    interrupted still does not leave a copy of somebody's record behind.
    """
    tmp = where or os.path.join(tempfile.gettempdir(),
                                f"mild-align-{os.getpid()}.wav")
    got = None
    fetched.last_error = ""
    fetched.swapped = None
    fetched.margin = None
    fetched.doubted = None
    try:
        # The copy this track was aligned against before, if there is one. The
        # search is not asked again: it would not return the same candidates
        # anyway, which is the whole reason this is remembered.
        # The copy itself, if it was kept. A pinned URL only promises the same
        # recording while YouTube will still serve it -- and tonight it would
        # not: three songs lost their pin to failed downloads and were silently
        # re-fetched as worse copies, one of them twenty times worse. Keeping
        # the audio makes the promise real, and makes a measurement repeatable
        # a week later.
        saved = _kept(tid) if tid else None
        if saved:
            yield str(saved)
            return
        pinned = LS.pinned_source(tid) if tid else ""
        if pinned:
            for _try in range(PIN_TRIES):
                got = fetch(pinned, tmp)
                if got:
                    yield got
                    return
            # Gone, or the far end refused, PIN_TRIES times over. Fall through
            # and choose again -- a pin is a preference, not a requirement.
            #
            # But say so. Swapping the recording under a measurement is the
            # difference between 6s of error and 23s on the same song, and it
            # used to happen in silence: the numbers moved and nothing said why.
            fetched.swapped = (pinned, fetch.last_error or "download failed")
            LS.pin_source(tid, "")
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
        for url, _dur in hits[:FETCH_TRIES]:
            got = fetch(url, tmp)
            if not got:
                why.append(fetch.last_error or "download failed")
                continue
            if words and decoys:
                # Listen before accepting it. Length and title agreeing is what
                # got us somebody else's track under ACHOO!'s name and a
                # stranger's recording under Labyrinth's -- both the right
                # length, both wrong, and both silently aligned for hours.
                # A transcript costs ~15s and settles it.
                mark = _sounds_like(got, words, decoys)
                fetched.margin = mark
                if mark is not None and mark < HEARD_MARGIN:
                    why.append(f"{url.rsplit('=', 1)[-1]} is a different "
                               f"recording ({mark*100:+.0f}%)")
                    if best is None or mark > best[0]:
                        best = (mark, url)
                    got = None
                    continue
            # Remembered before it is used, so the next run of this track
            # measures the same recording whatever the search says then.
            if tid:
                LS.pin_source(tid, url)
                _keep(tid, got)
            break
        if not got and best is not None:
            # Nothing passed. The least-wrong copy beats no copy at all, and
            # the caller is told what it is getting rather than guessing.
            got = fetch(best[1], tmp)
            fetched.doubted = best[0]
            if got and tid:
                LS.pin_source(tid, best[1])
        if hits and not got:
            fetched.last_error = (
                f"{len(hits)} copies at the right length, and "
                f"{'none of the ' + str(len(why)) if len(why) > 1 else 'the one'} "
                f"tried would download — {why[-1] if why else 'no reason given'}")
        yield got
    finally:
        for leftover in (tmp, tmp.rsplit(".", 1)[0] + ".webm",
                         tmp.rsplit(".", 1)[0] + ".m4a"):
            try:
                os.remove(leftover)
            except OSError:
                pass


fetched.last_error = ""
fetched.swapped = None      # (url, why) when a pinned copy was abandoned
fetched.margin = None       # how well the copy taken matched the words
fetched.doubted = None      # set when every copy failed and the best was kept


# --------------------------------------------------------------------------
# Where this stands, measured rather than hoped.
#
# The old Space, aligning against the full mix, placed every line of a control
# track but landed only 56% of them within half a second, with the worst tenth
# around 18 seconds out.
#
# Separating the vocal first was aimed squarely at the first half of that, and
# it worked. Scored against a song whose own word timings were already known
# (Red Hot Chili Peppers, "Can't Stop" -- 269s, 74 lines, 523 words, syllable
# -timed from Spicy Lyrics and used here as the answer key):
#
#     all 523 words placed          median error   +0.12s
#     69 lines comparable           mean |error|    0.37s
#     within 0.25s   67/69  (97%)   within 0.50s   68/69  (99%)
#
# That is the aligner no longer competing with the drums for the frames it is
# scoring. Two things are worth being plain about, though.
#
# The first is that a like-for-like figure is not available: the 56% above was a
# different track. What this shows is that a vocal-only alignment can be right
# to a fifth of a second across a whole song, not the size of the improvement.
#
# The second is the outlier, and it is the same outlier as before. One line --
# "Can't stop, addicted to the shindig", which the song sings several times --
# came out 16.4 seconds early, matched to the wrong repetition. Separation does
# nothing for this and no filter can see it. Forced alignment maps the text onto
# the audio monotonically and must consume every word it is given, so wherever
# the text says something the recording does not sing there, it stretches or
# squeezes the surrounding words to cover the gap, confidently.
#
# What fixes that is anchoring, and it is built: see _anchored. Measured on
# two songs where the single pass was visibly wrong --
#
#     Gravity      worst line 22.3s -> 4.6s, 3 lines over 8s -> 2, and ten
#                  lines Genius lists that the recording does not sing lost
#                  their invented timings instead of keeping them
#     Fading Wind  no trustworthy anchor exists, so it is left alone
#
# The second is the important one. A line-synced copy of the same WORDS is not
# a line-synced copy of the same RECORDING, and NetEase's "Fading Wind" is the
# proof: all 37 lines pair by text and its times belong to a shorter edit.
# Anchored on it, every line was dragged into the back half of the song --
# far worse than the problem being fixed. ANCHOR_SHARE is what refuses it, and
# nothing here matters more than that it keeps refusing it.
#
# So anchoring is not a filter and not a repair: it is a second walk over the
# same emission, between points a human already agreed on. Where those points
# do not exist, or do not agree about the clock, this is the same single pass
# it always was -- which is most of a library, since a song somebody has
# already line-synced well is not always the song that comes here.
#
# Stage three does not touch any of the above, and is worth being exact about
# for that reason. It divides words the aligner had already placed; it cannot
# move one, and the guard in _pieces exists to keep it that way. So the figures
# stand as they are -- the same words in the same places, with the boundaries
# inside them drawn where the pronunciation says rather than where the spelling
# does. On the control track it divided 146 of 669 syllables out of the middle
# of a word, and every line still read as the line in the document.
#
# What it fixed was linguistic rather than acoustic, and the four words this
# was built for are the whole list: hope stays whole, dumbed and trapped stay
# whole, packaged divides, around divides in front of the r. What it did not
# fix, and what no amount of it will: a chorus matched to the wrong repetition
# is still 16.4 seconds out, and now it is 16.4 seconds out in syllables.
# --------------------------------------------------------------------------
