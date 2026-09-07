"""A syllable-timed TTML for one song, timed by this model.

    python -m sync.sync ttml                      whatever Spotify is playing
    python -m sync.sync ttml "artist title"
    python -m sync.sync ttml "song" --format elrc

The words come from Spicy Lyrics -- the documents people uploaded, `source:
spl` -- and NOT from Apple Music's own word-synced lyrics, which are also in
that cache under `aml`. That is a hard filter, in one place, at `_spl_only`. It
matters twice over: the aml documents are somebody else's product, and a model
measured against a lyric it was also trained on is measuring nothing.

The timings come from the model and nothing else. If the fetched copy is
displaced against the master -- a re-upload with silence bolted on the front --
the shift is taken off before the alignment, so the file lines up with the
track the player is holding rather than with the copy the aligner could find.
See offset.py for why that is done by arithmetic on lengths and not by
guesswork on loudness.

The output goes through the player's own renderer, so the file is the same
shape as every other TTML in this project: the same <span> layout, the same
x-bg ad-libs, the same iTunes timing attribute.

SEPARATION IS OFF BY DEFAULT. The model reads the song as it was mixed. A
separated vocal is cleaner but it is also invented: demucs leaves smearing and
phantom onsets exactly where a quiet consonant sits under a cymbal, and a
timing model taught on those artefacts learns to time the artefact. Pass
--stem to turn separation back on; if you do, everything downstream has to be
stem too, because a model trained on one and run on the other is a domain
mismatch and will read as "the timings got worse".
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

from . import audio, ctcalign, model as M, offset, text, vocal

ALIGNER = pathlib.Path(__file__).resolve().parent.parent / "aligner"
sys.path.insert(0, str(ALIGNER))

SNAP = pathlib.Path.home() / ".cache/mild-lyrics/sync/spl"
COMMUNITY = "spl"


# ---------------------------------------------------------------- the lyric
def _spl_only(doc: dict, tid: str) -> dict:
    """`doc` if people wrote it, otherwise nothing.

    The cache holds three kinds of word-synced document -- `spl` uploaded by
    people, `aml` from Apple Music, `spt` from Spotify -- and they are not
    interchangeable for this purpose. Refusing loudly here is the point: a
    silent fallback to aml is exactly the bug that would make every number in
    the benchmark a little too good.
    """
    if not isinstance(doc, dict):
        return {}
    source = str(doc.get("source") or "")
    if source != COMMUNITY:
        raise SystemExit(
            f"the lyric cached for {tid} came from {source or 'nowhere'!r}, "
            f"not {COMMUNITY!r} (Spicy Lyrics). This model is only ever "
            f"pointed at community uploads -- play the song with Spicy Lyrics "
            f"so an spl document is cached, or pass --any-source to override.")
    return doc


def lyric(tid: str, cdp=None, any_source: bool = False) -> dict:
    """The spl document for a track, from the snapshot or from the player."""
    kept = SNAP / f"{tid}.json"
    if kept.exists():
        doc = json.loads(kept.read_text(encoding="utf-8"))
        return doc if any_source else _spl_only(doc, tid)
    import spicy_lyrics as SL
    if cdp is None:
        from spotify_dom import connect
        cdp = connect(9222, "spotify")
        if cdp is None:
            raise SystemExit("Spotify is not reachable on port 9222, and this "
                             "song is not in the snapshot -- start Spotify "
                             "with Spicetify, or run `sync snapshot` first.")
    got = cdp.evaluate(SL.JS_GET % SL._j(SL.CACHE_PREFIX, SL.IDB_NAME,
                                         SL.IDB_STORE, tid)) or {}
    doc = SL.payload(got.get("body") or {})
    if not doc:
        raise SystemExit(f"no lyric cached for {tid} -- play it once in "
                         f"Spotify and try again")
    return doc if any_source else _spl_only(doc, tid)


def _groups(doc: dict) -> list[dict]:
    """The document as things to time: one row per voice per line.

    A row is {"item": n, "role": "Lead"|"Background", "at": k, "words": [...]}.
    Both the word-synced documents and the plain ones come out the same shape,
    because the model does not care which it was given -- it is going to time
    every word from the audio either way.
    """
    import lyric_sources as LS
    import spicy_lyrics as SL
    rows = []
    for n, item in enumerate(LS._items(doc)):
        lead = item.get("Lead")
        if isinstance(lead, dict) and lead.get("Syllables"):
            words = SL.syllables_text(lead["Syllables"]).split()
        else:
            words = str(item.get("Text") or "").split()
        if words:
            rows.append({"item": n, "role": "Lead", "at": 0, "words": words})
        bg = item.get("Background")
        for k, g in enumerate(bg if isinstance(bg, list)
                              else ([bg] if isinstance(bg, dict) else [])):
            if not isinstance(g, dict):
                continue
            got = (SL.syllables_text(g.get("Syllables"))
                   if g.get("Syllables") else str(g.get("Text") or "")).split()
            if got:
                rows.append({"item": n, "role": "Background", "at": k,
                             "words": got})
    return rows


# ------------------------------------------------------------- the timings
def _cut(display: str, pieces: list[str]) -> list[str]:
    """Cut the word as WRITTEN at the boundaries found in the word as spelled.

    The model reads `dont` and the reader sees `don't`; the syllables have to
    be the reader's. So the display word is walked one character at a time,
    counting only the characters that survived flattening, and cut where those
    counts cross a boundary. Punctuation rides along with the piece it touches.
    """
    if len(pieces) < 2:
        return [display]
    # Cumulative, not per-piece: the counter walks the whole word once, so the
    # boundaries it is compared against have to be positions in the word.
    want, at = [], 0
    for piece in pieces[:-1]:
        at += len(piece)
        want.append(at)
    seen, out, buf = 0, [], ""
    for ch in display:
        buf += ch
        if text.flatten(ch):
            seen += 1
            if want and seen == want[0]:
                out.append(buf)
                buf, want = "", want[1:]
                # A trailing apostrophe or comma belongs to the piece before it.
    if buf:
        out.append(buf)
    return out or [display]


def _syllables(word: str, row: dict) -> list[dict]:
    """One word's syllables, timed from the characters the model placed."""
    flat = text.flatten(word)
    chars = row.get("chars") or []
    pieces = text.syllables(flat) if flat else [word]
    if not chars or len(chars) < len(flat) or len(pieces) < 2:
        return [{"Text": word, "StartTime": round(row["start"], 3),
                 "EndTime": round(row["end"], 3), "IsPartOfWord": False}]
    shown = _cut(word, pieces)
    out, at = [], 0
    for k, piece in enumerate(pieces):
        span = chars[at:at + len(piece)]
        at += len(piece)
        if not span:
            continue
        out.append({"Text": shown[k] if k < len(shown) else piece,
                    "StartTime": round(span[0][0], 3),
                    "EndTime": round(span[-1][1], 3),
                    "IsPartOfWord": True})
    if not out:
        return [{"Text": word, "StartTime": round(row["start"], 3),
                 "EndTime": round(row["end"], 3), "IsPartOfWord": False}]
    out[-1]["IsPartOfWord"] = False
    out[-1]["EndTime"] = round(max(out[-1]["EndTime"], row["end"]), 3)
    return out


# What the audio itself is allowed to say, swept on the 17 gold songs and
# left mid-range rather than at the edge of what was tried: per-song mean
# 0.395 -> 0.327s, worst-30 2.09 -> 1.62s, median 0.087 -> 0.064s, 12 of 17
# songs usable against 10. GATE is nats of blank bonus a silent frame gets;
# ATTACK is how far a word start may be pulled back onto a sung attack.
GATE = 2.0
ATTACK = 0.12
SUSTAIN = 0.8
# How far a word start may reach back onto the attack that began a held note.
# CTC puts a letter where it is surest of it, which for a vowel held a second
# is inside the note rather than at its start: "all" in Guilty All the Same
# begins on a clear attack at 95.78s and was placed at 96.39s, leaving a
# 0.64s hole in the sweep with unbroken singing under it. With this it starts
# at 95.75s and runs the full 1.06s.
#
# Swept on the 17 gold songs first: 0.317s at no reach, 0.317s at 0.4, 0.316s
# at 0.8 — neutral, because the conditions are narrow enough that it rarely
# fires. Neutral globally and right locally is the profile that earns a
# default; the duration floor had the opposite one and stays off.

# Below this median word confidence, a mixture alignment is not to be trusted
# and separation is worth its cost. Set from the gold songs -- see confidence()
# -- rather than picked: the failing songs and the good ones separate cleanly
# on this number, which is the mean probability the model gave the letters it
# actually placed.
WEAK = 0.35

# How far a per-song bias correction may reach. The model's own standing
# lateness is 0.048s (measured over the gold songs), and a song whose words sit
# a quarter-second from every attack it lands on has something worse than a
# bias wrong with it -- so a big number here would be a licence to paper over a
# bad alignment rather than to square a good one.
LEAN = 0.15
# ...and OFF by default, because it was measured and it is wrong.
#
# Against gc's own hand-timed Love Blur, squaring the file to its sung attacks
# took 400 words from 0.068s mean to 0.143s, and from 45% of words inside 50 ms
# to 6%. The premise -- that a word starts where its attack is -- is not how a
# person times a lyric. He said so before this was written: "people
# synchronizing may synchronize what they hear and what looks like it's good,
# which is why often even my own synchronizations don't line up with a
# spectrogram." His words sit about 90 ms after the attack, consistently, and
# that is the thing being synchronised to.
#
# Kept, because it measures something real and says it out loud (a file that
# sits 0.4s from every attack it lands on has a problem worth knowing about),
# but it does not move times unless asked.


def _timed(rows: list[dict], logp, device: str, lag: float = 0.0,
           log=None, boundary=None, present=None, onset=None,
           gate: float = 0.0, attack: float = 0.0,
           sustain: float = 0.0) -> list[dict]:
    """Every row's words, timed. Lead over the song, ad-libs inside their line.

    The lead voices are one long forced alignment, which is what makes a
    repeated chorus land on the right repeat: the path cannot go backwards, so
    the fourth chorus cannot borrow the second's timing.

    The ad-libs are not in that sequence, because they are not sung in it. An
    answering voice comes in over the end of the line it answers or just after
    it, and threading it into the lead's sequence forces the lead to wait for
    it. Each one is aligned on its own inside the window of the line it belongs
    to, plus a little after, where it either is or is not.
    """
    lead = [r for r in rows if r["role"] == "Lead"]
    flat, owner = [], []
    for r in lead:
        for w in r["words"]:
            flat.append(w)
            owner.append(r)
    placed = ctcalign.words(logp, flat, device, boundary=boundary,
                            present=present, gate=gate,
                            onset=onset, attack=attack, sustain=sustain)
    by_index = {row["i"]: row for row in placed}

    for r in lead:
        r["timed"] = []
    for k, r in enumerate(owner):
        got = by_index.get(k)
        r["timed"].append(dict(got, word=flat[k]) if got else
                          {"word": flat[k], "start": None, "end": None,
                           "score": 0.0, "chars": []})

    # Any line the alphabet could not spell at all keeps no times; fill it from
    # its neighbours so the file has no holes in it.
    _fill(lead)

    for r in rows:
        if r["role"] == "Lead":
            continue
        line = next((x for x in lead if x["item"] == r["item"]), None)
        window = _window(line, lead)
        r["timed"] = _inside(r["words"], logp, window, device, boundary,
                             present=present, onset=onset,
                             gate=gate, attack=attack)

    if lag:
        for r in rows:
            for w in r["timed"]:
                if w.get("start") is not None:
                    w["start"] += lag
                    w["end"] += lag
                    w["chars"] = [(a + lag, b + lag) for a, b in w.get("chars") or []]
    return rows


def _window(line: dict | None, lead: list[dict]) -> tuple[float, float]:
    """When the line an ad-lib answers was sung, plus a beat after it."""
    if not line or not line.get("timed"):
        return (0.0, 0.0)
    times = [w for w in line["timed"] if w.get("start") is not None]
    if not times:
        return (0.0, 0.0)
    after = next((x for x in lead if x["item"] > line["item"]
                  and any(w.get("start") is not None for w in x["timed"])), None)
    end = max(w["end"] for w in times) + 2.0
    if after:
        nxt = min(w["start"] for w in after["timed"] if w.get("start") is not None)
        end = min(end, nxt)
    return (min(w["start"] for w in times), max(end, max(w["end"] for w in times)))


def _inside(words: list[str], logp, window: tuple[float, float],
            device: str, boundary=None, present=None, onset=None,
            gate: float = 0.0, attack: float = 0.0,
            floor: float = 0.0) -> list[dict]:
    """Time a few words inside one window, or leave them untimed."""
    a, b = window
    # Clamped rather than refused: the window reaches a couple of seconds past
    # the line it answers, and the last line of a song reaches past the end of
    # the song. That is not a reason to leave its ad-lib untimed.
    lo = max(0, audio.frames(a))
    hi = min(logp.shape[0], audio.frames(b))
    a = audio.seconds(lo)
    # HOW MANY FRAMES THIS ACTUALLY NEEDS: the tokens the lattice must pass
    # through, which is what ctcalign tests too -- not the length of the
    # written line. Those differ by more than punctuation. The word text
    # carries the zero-width joiners the renderer puts between syllables, so
    # "Moet om drie uur op, kom aan om twee voor drie" measures 56 characters
    # against 45 real tokens, and the window that holds its TRUE 1.14s span --
    # 58 frames, comfortably enough -- was being refused as impossible.
    need = len(text.spell(words)[0])
    if hi - lo < need:
        return [{"word": w, "start": None, "end": None, "score": 0.0,
                 "chars": []} for w in words]
    local_boundary = None if boundary is None else boundary[lo:hi]
    got = ctcalign.words(logp[lo:hi], words, device, prior_from=logp,
                         boundary=local_boundary,
                         present=None if present is None else present[lo:hi],
                         gate=gate,
                         onset=None if onset is None else onset[lo:hi],
                         attack=attack, floor=floor)
    by_index = {r["i"]: r for r in got}
    out = []
    for k, w in enumerate(words):
        row = by_index.get(k)
        if not row:
            out.append({"word": w, "start": None, "end": None, "score": 0.0,
                        "chars": []})
            continue
        out.append({"word": w, "start": row["start"] + a, "end": row["end"] + a,
                    "score": row["score"],
                    "chars": [(x + a, y + a) for x, y in row["chars"]]})
    return out


def _fill(lead: list[dict]) -> None:
    """Give untimed words something, borrowed from the words around them."""
    flat = [w for r in lead for w in r["timed"]]
    last = 0.0
    for w in flat:
        if w.get("start") is None:
            w["start"], w["end"] = last, last + 0.2
        last = w["end"]


CLOSE = 0.5          # a gap up to this long is the sweep continuing, not a pause


def sweep(syls: list[dict]) -> list[dict]:
    """Make a line's syllables run into each other, the way a hand-timed one does.

    Measured against gc's own file for the same song: 89% of his syllables
    begin within 20 ms of where the last one ended -- the highlight never
    stops moving until there is a real pause. Ours were contiguous 23% of the
    time, held for 0.140s against his 0.228s, and left a 40 ms hole three times
    in four. Every endpoint was within 0.02s of his, and it still read as
    words ending early, because what a viewer sees is the SWEEP, not the
    endpoint.

    So a syllable runs to wherever the next one starts, unless the gap is long
    enough to be a real pause (CLOSE). Where the model has put two syllables
    out of order -- which the monotone path cannot do, but the per-character
    distribution inside a word can -- the TIMES are pulled straight here
    rather than written into a file no player can sweep.

    The times, and never the order. This used to sort the line by StartTime,
    which reads the clock as the authority on what comes first; the text is.
    The flags that spell the words travel with the syllables they are on, so
    sorting a line whose times cross splices the words into each other --
    "knockin', feel the aura" came back as "knofeel the ckin', aura" the
    moment a document carried a syllable held over the ones after it. Lines
    like that are no longer a fault to be corrected on the way in (see
    lyric_sources._repair), so they reach here and must leave spelling what
    they spelled. On a line whose times already ascend -- every line the model
    itself produces -- pulling forwards and sorting do the same thing, so
    nothing about the ordinary case has changed.
    """
    out = []
    for syl in syls:
        one = dict(syl)
        if out and one["StartTime"] < out[-1]["StartTime"]:
            one["StartTime"] = out[-1]["StartTime"]
        out.append(one)
    for a, b in zip(out, out[1:]):
        a["StartTime"] = round(min(a["StartTime"], b["StartTime"]), 3)
        gap = b["StartTime"] - a["EndTime"]
        if a["EndTime"] > b["StartTime"] or 0 < gap <= CLOSE:
            a["EndTime"] = b["StartTime"]
        a["EndTime"] = round(max(a["EndTime"], a["StartTime"]), 3)
    if out:
        out[-1]["EndTime"] = round(max(out[-1]["EndTime"], out[-1]["StartTime"]), 3)
    return out


def _ordered(syls: list[dict], floor: float | None = None) -> list[dict]:
    """One run of syllables, in order, none starting before `floor`."""
    out, last = [], floor
    for syl in syls:
        one = dict(syl)
        if last is not None and one["StartTime"] < last:
            one["StartTime"] = last
        one["EndTime"] = max(one["EndTime"], one["StartTime"])
        last = one["StartTime"]
        out.append(one)
    # Ends second: moving a start can push it past the end that was written
    # for it, and an end may not reach into the syllable after it.
    for a, b in zip(out, out[1:]):
        a["EndTime"] = round(min(max(a["EndTime"], a["StartTime"]),
                                 b["StartTime"]), 3)
        a["StartTime"] = round(a["StartTime"], 3)
    if out:
        out[-1]["StartTime"] = round(out[-1]["StartTime"], 3)
        out[-1]["EndTime"] = round(max(out[-1]["EndTime"],
                                       out[-1]["StartTime"]), 3)
    return out


def settle(items: list[dict]) -> list[dict]:
    """Times that only ever move forwards, across the WHOLE document.

    sweep() sorts one line's syllables and stops there, which leaves three
    ways for a span to begin before the span in front of it.

    HONESTLY: this is a guard, not a repair. It was written to fix "8
    out-of-order spans in love hate, 23 in Love Blur", and those numbers were a
    counting mistake -- they came from scanning every `begin=` in document
    order, which includes the x-bg wrapper of a backing vocal that legitimately
    starts before the lead span printed above it. Audited per voice, the files
    were already clean, before this existed. The three routes below are real
    in the code and reachable in principle; none of them was firing on the
    songs measured. It stays because it is cheap and tested, and because a
    player sweeping a backwards time looks broken however rare that is.

      * a Background run is aligned in its own window (_inside) and compared
        to nothing, so it can start before its own line or land inside the
        next one;
      * _fill invents `last, last + 0.2` for a word the alphabet cannot spell
        and never reconciles it against the real word that follows;
      * the end refinement may push a word's end up to 0.5s later, past where
        the next line begins.

    A player sweeps a highlight through these times in the order they are
    written. Backwards times are not a small inaccuracy to it -- the highlight
    jumps, or stalls, and the line looks broken however close the numbers are.

    Lead lines form one chain, each starting no earlier than the line before.
    Background runs are clamped inside their own line instead of joining that
    chain, because a backing vocal genuinely sings AT THE SAME TIME as the
    lead and must be allowed to overlap it.
    """
    floor = None
    for item in items:
        lead = item.get("Lead")
        lo = hi = None
        if isinstance(lead, dict) and lead.get("Syllables"):
            syls = _ordered(lead["Syllables"], floor)
            lead["Syllables"] = syls
            lo = lead["StartTime"] = item["StartTime"] = syls[0]["StartTime"]
            hi = lead["EndTime"] = item["EndTime"] = max(
                s["EndTime"] for s in syls)
            # The LAST syllable's start, not the line's: carrying the line
            # start forward lets the next line legally begin before this
            # line's own later syllables, which is the same broken sweep one
            # level up.
            floor = syls[-1]["StartTime"]
        bgs = item.get("Background")
        bgs = bgs if isinstance(bgs, list) else ([bgs] if isinstance(bgs, dict)
                                                 else [])
        for bg in bgs:
            if not isinstance(bg, dict) or not bg.get("Syllables"):
                continue
            syls = bg["Syllables"]
            if lo is not None:
                # Only what sticks out is moved. A run that fell entirely
                # outside its line collapses onto the nearer edge, which is
                # degenerate but ordered -- and it is a rare enough case that
                # hiding it inside a plausible-looking spread would be worse.
                syls = [dict(x, StartTime=min(max(x["StartTime"], lo), hi),
                             EndTime=min(max(x["EndTime"], lo), hi))
                        for x in syls]
            syls = _ordered(syls, lo)
            bg["Syllables"] = syls
            bg["StartTime"] = syls[0]["StartTime"]
            bg["EndTime"] = max(s["EndTime"] for s in syls)
    return items


# A line whose words average below this share of the song's own median word is
# not being sung fast, it is being squeezed. Measured on Krantenwijk: the line
# the listener flagged averaged 0.145s against the song's 0.24s, with a 0.060s
# word in it, because the path had to reach a line it was sure of.
CRUSHED = 0.70
# What that line is re-aligned with. A floor of 60 ms forbids almost nothing a
# person writes -- 0.12% of 27,736 hand-timed words are shorter -- and applied
# to the WHOLE song it costs more than it wins (0.327 -> 0.374 on the gold
# songs, every increment worse than the last). Applied only to lines that are
# actually crushed, it is the 0.16s it won on that line without the 0.047s it
# lost everywhere else. Off unless asked for, until that is measured too.
RELIEF = 0.06


# ------------------------------------------------- the text's own duration
#
# HOW LONG THE WORDS SHOULD TAKE, which is the one thing CTC never asks.
#
# The search scores every frame independently, so a line spread over 1.7s of
# audio costs exactly what the same line packed into 1.1s costs. Nothing in it
# can say "eleven syllables at this tempo do not fill that much room". That is
# the whole of the failure the listener keeps reporting: a line starts early,
# runs slow, and finishes correctly, because its end was pinned by the line
# after it and its start had nothing holding it.
#
# Measured on Krantenwijk, 1:35. "Moet om drie uur op, kom aan om twee voor
# drie" was placed 95.26 -> 97.01, eleven words at 0.156s each. The reference
# puts it at 95.89, and the line after it -- which the listener confirms is on
# time -- begins at 97.03. So the truth is 1.14s for those words, 0.104s each,
# and the aligner had given the line HALF AGAIN the room it needed.
#
# Note what this means for _uncrush, which fired on that very line: measured
# against the song's median word of 0.220s it reads as squeezed, and the remedy
# is to give it MORE room. Against its own syllables it reads as over-long. A
# song-relative pace gets the sign wrong on exactly the lines that fail, which
# is why the prior here counts syllables instead.
UNEVEN = 1.35         # how lopsided a pair's per-syllable share must be
REACH = 0.30          # seconds a proposed start may move onto a real attack
AGREE = 0.05          # seconds: a word start "lands on" an attack this close


def _beats(word: str) -> int:
    """Roughly how many syllables a written word has. Vowel groups, not
    linguistics -- the same rule sync.text.syllables cuts on."""
    return len(re.findall(f"[{text.VOWELS}]+", word.lower())) or 1


def _lands(got: list[dict], marks: list[float]) -> float:
    """The share of these word starts that sit on a measured sung attack.

    The adoption test, and deliberately reference-free: it asks the audio, not
    the alphabet, so it works on a language the model was never trained on.
    """
    if not got or not marks:
        return 0.0
    import bisect
    hit = 0
    for w in got:
        k = bisect.bisect_left(marks, w["start"])
        for t in marks[max(0, k - 1):k + 2]:
            if abs(t - w["start"]) <= AGREE:
                hit += 1
                break
    return hit / len(got)


def _repace(rows: list[dict], logp, device: str, boundary=None, present=None,
            onset=None, gate: float = 0.0, attack: float = 0.0,
            log=None) -> int:
    """Share the room between two lines in proportion to their syllables.

    WHY NOT A PACE. The first version of this measured the song's own seconds
    per syllable and pulled back any line that ran longer than its text could
    fill. It does not fire on the case it was built for. Krantenwijk reads
    0.235s a syllable across the song, but that median is set by its sung
    chorus; the rapped verse runs at half of it, so the mis-timed line -- 11
    syllables in 1.78s, 0.162s each -- is ALREADY faster than pace, and an
    over-run trigger can never see it. Any song that alternates rapping and
    singing breaks a single global pace the same way.

    What survives that is the ratio, not the rate. Two lines that sit against
    each other divide a fixed piece of audio, and the text says how it should
    divide: twelve syllables and eleven syllables want the boundary near the
    middle, wherever the pair happens to sit and however fast it is sung. No
    estimate of tempo appears anywhere in that, which is exactly why the mixed
    verse cannot break it.

    Measured on the case: "Nu live op je stage, en breng energie" was given
    1.36s for 12 syllables while "Moet om drie uur op, kom aan om twee voor
    drie" took 1.78s for 11 -- the first squeezed, the second expanding early
    into the room that left. Proportional sharing puts their boundary at
    95.51s against a reference of 95.89s, where the aligner had put it at
    95.21s.

    Only the boundary BETWEEN the pair moves. The outer edges are held by the
    lines on either side, so nothing can walk away from the recording -- the
    failure that retired anchoring.

    AND IT LOSES. Off by default, and this is why. On the 17 hand-timed songs,
    against 0.317s / 1.61s worst-30 / 12 of 17 usable:

        with --repace   0.377s | worst-30 2.25s | 10 of 17 usable

    Sixteen songs moved, THIRTEEN of them worse: Ash In The Wind 0.115 ->
    0.439, Solar Eclipses 0.164 -> 0.393, DM DOKURO 0.155 -> 0.352. Held notes
    are what breaks it -- a sung line spends its syllables at wildly different
    speeds, so the room a pair "should" share by syllable count is not the room
    the singing actually uses, and the boundary is moved off a correct place.

    It does not fix the case it was built for either. Krantenwijk 1:35 needs
    its two lines at 0.170 and 0.104 seconds a syllable, 1.6x apart; a rule
    that shares by syllable count cannot produce a 1.6x split, so the pair is
    left where it was. The information that identifies that line is acoustic,
    not textual: the strongest attack in the window (0.94 at 95.96s) is the
    true start, and the aligner began on a weaker one (0.54 at 95.26s).

    NOTE ON _lands. The adoption guard did not save this. Onset agreement rose
    on songs whose real error grew, so agreement with attacks is NOT a proxy
    for correctness -- the same reason `lean` was measured worse: a person
    times a little AFTER the attack, and a pass that maximises attack agreement
    walks away from the reference while its own number improves.
    """
    import statistics
    lead = [r for r in rows if r["role"] == "Lead"]
    spans = [[w for w in r["timed"] if w.get("start") is not None] for r in lead]
    syls = [sum(_beats(w) for w in r["words"]) for r in lead]
    marks = vocal.attacks(onset) if onset is not None else []
    if not marks:
        return 0

    fixed = 0
    for n in range(1, len(lead)):
        one, two = spans[n - 1], spans[n]
        if len(one) < 3 or len(two) < 3 or not syls[n - 1] or not syls[n]:
            continue
        lo, hi = one[0]["start"], two[-1]["end"]
        # Only a pair that actually abuts. A real pause between two lines is
        # room that belongs to NEITHER of them, and dividing it would drag the
        # second line back into the silence.
        if two[0]["start"] - one[-1]["end"] > 0.5 or hi - lo < 0.8:
            continue
        # How unevenly they are sharing it now, per syllable. A pair singing at
        # honestly different speeds is ordinary, so this has to be a real gap
        # before anything moves.
        was = one[-1]["end"]
        pace_one = (one[-1]["end"] - lo) / syls[n - 1]
        pace_two = (hi - two[0]["start"]) / syls[n]
        if not pace_one or not pace_two:
            continue
        odds = max(pace_one, pace_two) / min(pace_one, pace_two)
        if odds < UNEVEN:
            continue
        split = lo + (hi - lo) * syls[n - 1] / (syls[n - 1] + syls[n])
        near = [t for t in marks if abs(t - split) <= REACH]
        if not near:
            continue
        split = min(near, key=lambda t: abs(t - split))
        if abs(split - was) < 0.10 or split - lo < 0.30 or hi - split < 0.30:
            continue
        head = _inside(lead[n - 1]["words"], logp, (lo, split), device,
                       boundary=boundary, present=present, onset=onset,
                       gate=gate, attack=attack)
        tail = _inside(lead[n]["words"], logp, (split, hi), device,
                       boundary=boundary, present=present, onset=onset,
                       gate=gate, attack=attack)
        got = [w for w in head + tail if w.get("start") is not None]
        if len(got) != len(lead[n - 1]["words"]) + len(lead[n]["words"]):
            continue
        # THE ADOPTION GUARD, on evidence the audio supplies rather than the
        # alphabet. Anchoring had none, and that is how two of its songs
        # reached the output tens of seconds wrong.
        if _lands(got, marks) < _lands(one + two, marks):
            continue
        lead[n - 1]["timed"], lead[n]["timed"] = head, tail
        spans[n - 1] = [w for w in head if w.get("start") is not None]
        spans[n] = [w for w in tail if w.get("start") is not None]
        fixed += 1
        if log:
            log(f"lines {n-1}/{n} shared {hi - lo:.2f}s as "
                f"{syls[n-1]}/{syls[n]} syllable(s) — boundary "
                f"{was:.2f}s -> {split:.2f}s")
    return fixed

# ------------------------------------------------ the dominant attack
#
# A line that starts on the WRONG attack. In dense rap every syllable throws an
# attack, so the search can begin a line most of a second early on a real one
# and never notice: every frame it crosses is genuinely being sung, just by the
# line before. The ordinary start refinement cannot help -- it reaches 0.12s
# and only ever pulls a start EARLIER, and this fault needs the start LATER.
#
# What separates the two candidates is not the lyric but how hard the singer
# hits. Measured on Krantenwijk 1:35: the true start at 95.96s is the largest
# flux peak anywhere in the window, 0.94, while the aligner began the line at
# 95.26s on a peak of 0.54. The line after it -- which the listener confirms is
# correctly timed -- has no such peak anywhere ahead of it (0.49 at its start,
# nothing above 0.47 for the next half second), so nothing here moves it. That
# asymmetry is the whole rule.
#
# Unlike _uncrush and _repace, this does NOT redistribute room between two
# lines. Those hold both outer edges and can only relocate an error, which is
# what the listener heard when the fault moved from 1:35 to 1:37. Here one
# edge -- a line's own start -- is moved onto acoustic evidence, and the
# following line is not touched at all.
WANDER = 1.00         # seconds a line start may be moved later, at most
DOMINANT = 0.75       # how strong the attack it moves onto must be, 0..1
LOUDER = 1.5          # and how much louder than the attack it is leaving
# How much of its letter confidence a line may lose by moving. 1.0 means it
# must not lose any, which is what ships.
TRUST = 1.0


def _onattack(rows: list[dict], logp, device: str, boundary=None, present=None,
              onset=None, gate: float = 0.0, attack: float = 0.0,
              log=None) -> int:
    """Start a line on the loudest attack it plausibly begins on.

    The guard is the model's own letter confidence, NOT agreement with the
    attacks. Agreement fails as a test here for the same reason `lean` was
    measured worse: it is the quantity being maximised, so it rises on songs
    whose real error grows. _repace was adopted on it and lost 13 of 17 songs.
    Confidence is independent of what this pass optimises, which is why the
    separation trigger can be trusted to the same kind of test.

    MEASURED on the 17 hand-timed songs, against 0.317s / 1.61s worst-30:

        --onattack            0.317s | p90 0.608 | per word 0.271 | 3 songs
                              moved, ALL 3 better, none worse
        the same, TRUST 0.4   0.340s | p90 0.696 | per word 0.296 | 17 songs
                              moved, 16 of them WORSE

    So the guard is the whole thing, not the rule it guards. At full strictness
    five lines move across seventeen songs and nothing is ever damaged; let a
    line spend 60% of its confidence to reach a louder attack and the pass
    turns destructive -- DM DOKURO 0.155 -> 0.223, Undead 0.086 -> 0.135.

    Off by default all the same: never losing is not the same as winning, and
    on the headline mean this is a tie.

    AND IT DOES NOT REACH THE CASE IT WAS BUILT FOR. Krantenwijk 1:35 has its
    true start on the loudest attack in the window (0.94 at 95.96s) against the
    0.54 the aligner chose, all eleven words fit there -- and the model's
    confidence FALLS from 0.043 to 0.018 when they are put in the right place.
    It hears the lyric better where the lyric is not. No decode-time rule
    overrules that; 0.043 is a quarter of what Dutch normally reads on this
    encoder, so the passage is a hearing problem, not a search problem.
    """
    import statistics
    if onset is None:
        return 0
    lead = [r for r in rows if r["role"] == "Lead"]
    spans = [[w for w in r["timed"] if w.get("start") is not None] for r in lead]
    marks = vocal.attacks(onset, floor=0.0)
    if not marks:
        return 0
    flux = {round(t, 3): float(onset[int(round(t / audio.FRAME))])
            for t in marks
            if int(round(t / audio.FRAME)) < len(onset)}

    fixed = 0
    for n, (row, got) in enumerate(zip(lead, spans)):
        if len(got) < 3:
            continue
        began, end = got[0]["start"], got[-1]["end"]
        here = max((v for t, v in flux.items() if abs(t - began) <= 0.06),
                   default=0.0)
        ahead = [(t, v) for t, v in flux.items()
                 if began + 0.10 < t <= min(began + WANDER, end - 0.30)]
        if not ahead:
            continue
        when, loud = max(ahead, key=lambda x: x[1])
        if loud < DOMINANT or loud < LOUDER * max(here, 1e-6):
            continue
        again = _inside(row["words"], logp, (when, end), device,
                        boundary=boundary, present=present, onset=onset,
                        gate=gate, attack=attack)
        placed = [w for w in again if w.get("start") is not None]
        if len(placed) != len(row["words"]):
            continue
        was = statistics.mean(w.get("score", 0.0) for w in got)
        now = statistics.mean(w.get("score", 0.0) for w in placed)
        if now < TRUST * was:
            continue
        row["timed"] = again
        spans[n] = placed
        fixed += 1
        if log:
            log(f"line {n} began {began:.2f}s on a {here:.2f} attack — "
                f"a {loud:.2f} one at {when:.2f}s, started there instead")
    return fixed


def _uncrush(rows: list[dict], logp, device: str, boundary=None, present=None,
             onset=None, gate: float = 0.0, attack: float = 0.0,
             floor: float = RELIEF, log=None) -> int:
    """Re-time only the lines that were squeezed, and only those.

    A global duration floor was measured and refused: it smears every word
    leftward to make room, and the `early` share climbs with it (31% at no
    floor, 40% at 80 ms). What it is good at is the case it was built for, so
    it is spent there and nowhere else.

    The window a line is re-solved in is bounded by its neighbours, which are
    not being re-solved -- so a line can be relieved without any other line
    moving, and the document stays monotone by construction.
    """
    import statistics
    lead = [r for r in rows if r["role"] == "Lead"]
    spans = [[w for w in r["timed"] if w.get("start") is not None] for r in lead]
    every = [w["end"] - w["start"] for got in spans for w in got]
    if len(every) < 30:
        return 0
    typical = statistics.median(every)
    fixed = 0
    for n, (row, got) in enumerate(zip(lead, spans)):
        if len(got) < 3:
            continue
        mine = statistics.mean(w["end"] - w["start"] for w in got)
        if mine >= CRUSHED * typical:
            continue
        # WITH THE LINE BEFORE IT, because that is where the fault is.
        #
        # A crushed line is not crushed on its own account: the line before it
        # ran long, took the attack this one should have started on, and left
        # it too little room. Re-solving this line alone inside a window that
        # begins at its neighbour's end cannot fix that -- the window starts at
        # exactly the wrong boundary and the start has nowhere to go.
        # Measured on Krantenwijk: the line was still at 95.23s afterwards,
        # against a reference of 95.89s, unchanged to the millisecond.
        #
        # So the pair is re-solved together and the boundary between them is
        # allowed to move. Nothing outside the pair is touched.
        if not n or not spans[n - 1]:
            continue
        prior = lead[n - 1]
        lo = spans[n - 1][0]["start"]
        after = (min((w["start"] for w in spans[n + 1]),
                     default=audio.seconds(logp.shape[0]))
                 if n + 1 < len(spans) else audio.seconds(logp.shape[0]))
        hi = max(got[-1]["end"], min(after, got[-1]["end"] + 1.0))
        if hi - lo < 0.4:
            continue
        both = list(prior["words"]) + list(row["words"])
        again = _inside(both, logp, (lo, hi), device, boundary=boundary,
                        present=present, onset=onset, gate=gate, attack=attack,
                        floor=floor)
        if any(w.get("start") is None for w in again):
            continue                      # it would not fit; leave it alone
        head, tail = again[:len(prior["words"])], again[len(prior["words"]):]
        if not tail:
            continue
        was = mine
        now = statistics.mean(w["end"] - w["start"] for w in tail)
        if now <= was:
            continue                      # no relief, so no change
        prior["timed"], row["timed"] = head, tail
        spans[n - 1] = [w for w in head if w.get("start") is not None]
        fixed += 1
        if log:
            log(f"line {n + 1} was squeezed ({was:.3f}s a word against the "
                f"song's {typical:.3f}s) — re-timed with the line before it "
                f"at {now:.3f}s, boundary now {tail[0]['start']:.2f}s")
    return fixed


# ------------------------------------------------------------- the document
def document(doc: dict, rows: list[dict]) -> dict:
    """The cache's own document shape, with our times in it.

    Rebuilt rather than edited in place: a document that came in unsynced has
    no Syllables to edit, and one that came in word-synced must not keep a
    single one of its old times or the file would be half ours and half theirs
    with no way to tell which line is which.
    """
    import copy
    import lyric_sources as LS
    out = copy.deepcopy(doc)
    items = LS._items(out)
    for r in rows:
        syls = []
        for w in r["timed"]:
            if w.get("start") is None:
                continue
            syls.extend(_syllables(w["word"], w))
        if not syls:
            continue
        syls = sweep(syls)
        group = {"Syllables": syls,
                 "StartTime": syls[0]["StartTime"],
                 "EndTime": syls[-1]["EndTime"]}
        item = items[r["item"]]
        if r["role"] == "Lead":
            item["Lead"] = group
            item["Text"] = " ".join(r["words"])
            item["StartTime"] = group["StartTime"]
            item["EndTime"] = group["EndTime"]
        else:
            bg = item.get("Background")
            bg = bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else [])
            while len(bg) <= r["at"]:
                bg.append({})
            bg[r["at"]] = group
            item["Background"] = bg
    settle(items)
    out["Type"] = "Syllable"
    out["source"] = COMMUNITY
    out["SyncedBy"] = "mild-lyrics/sync"
    return out


_HELD: dict[tuple, tuple] = {}


def held_model(ckpt, device: str, keep: bool = True):
    """The model, loaded once and kept, or loaded fresh each time.

    Loading costs 4.0s and listening to a whole song costs 0.5s, so a player
    that drops the model between songs spends eight times longer starting the
    engine than driving it. It is 1.11 GB of VRAM to hold -- the reason the
    player has a setting for dropping it was the OLD chain, which held three
    models and 4.1 GB.
    """
    key = (str(ckpt), device)
    if keep and key in _HELD:
        return _HELD[key]
    got = M.load(ckpt, device)
    if keep:
        _HELD.clear()               # one at a time; two would be 2.2 GB
        _HELD[key] = got
    return got


def against(doc: dict, path: str, ckpt, device: str = "cuda",
            stem: bool = False, spare: float = 0.4, log=print,
            gate: float | None = None, attack: float | None = None,
            sustain: float | None = None, stop=None,
            keep: bool = False) -> dict | None:
    """Time a document somebody else supplied, against a file on disk.

    make() owns the whole errand: it finds the lyric, fetches a copy, decides
    about separation. This is for a caller that already has both -- the player,
    which has its own document from its own chain and its own copy of the audio
    already downloaded, and wants only the timing part.

    Returns None if the audio is too short to hold the words, which is the one
    failure that is not an exception.
    """
    import torch
    device = device if torch.cuda.is_available() else "cpu"
    net, rest = held_model(ckpt, device, keep)
    calibration = float(rest.get("calibration") or 0.0)
    rows = _groups(doc)
    if not rows:
        return None
    wave, rate = audio.read(path)
    mono = audio.mono16k(wave, rate)
    if stem:
        import local_align as LA
        dev, win, _ = LA.room("gpu", LA.DEMUCS_COST, LA.DEMUCS_WINDOW, spare)
        sep, srate = LA.separate(wave, rate, dev, win, LA.MODEL, None, None)
        mono = audio.mono16k(sep, srate)
        LA.release()
    if stop is not None and stop():
        return None
    logp, boundary = M.emit(net, mono, device, return_boundary=True)
    if not getattr(net, "has_boundary", True):
        boundary = None
    want_gate = GATE if gate is None else gate
    want_attack = ATTACK if attack is None else attack
    reach = SUSTAIN if sustain is None else sustain
    present = onset = None
    if want_gate > 0 or want_attack > 0 or reach > 0:
        from . import vocal
        if want_gate > 0:
            present = vocal.activity(mono, logp.shape[0])
        if want_attack > 0 or reach > 0:
            onset = vocal.onsets(mono, logp.shape[0])
    rows = _timed(rows, logp, device, lag=-calibration, log=log,
                  boundary=boundary, present=present, onset=onset,
                  gate=want_gate, attack=want_attack, sustain=reach)
    out = document(doc, rows)
    placed = sum(1 for r in rows for w in r["timed"] if w.get("start") is not None)
    out["_placed"] = [placed, sum(len(r["words"]) for r in rows)]
    return out


# ------------------------------------------------------------------- the job
def _sibling(ckpt):
    """The stem-trained model beside a mixture one, if it is on disk."""
    p = pathlib.Path(ckpt)
    mate = p.with_name(p.stem + "-stem" + p.suffix)
    return mate if mate.exists() else None


def confidence(rows: list[dict]) -> float:
    """How sure the model was of the words it placed -- the median, 0 to 1.

    The median rather than the mean, because one word the alphabet mangled
    should not condemn a song, and one word placed perfectly should not save
    one. A song the model cannot hear scores low across nearly every word.
    """
    import statistics
    said = [w["score"] for r in rows for w in r["timed"]
            if w.get("start") is not None and w.get("score")]
    return float(statistics.median(said)) if said else 0.0


def make(meta: dict, tid: str, ckpt, device: str = "cuda",
         stem: bool | None = None, spare: float = 0.4,
         any_source: bool = False, log=print,
         gate: float | None = None, attack: float | None = None,
         fallback=None, lean: bool = False, uncrush: bool = False,
         sustain: float | None = None, repace: bool = False,
         onattack: bool = False) -> dict:
    """Fetch, separate, align, and hand back a document ready to render.

    `stem` is three-valued. True always separates, False never does, and None
    -- the default -- aligns on the mixture first and only pays for separation
    if the result looks weak. Separation costs about nine seconds a song and is
    not always an improvement: measured on the gold songs it rescued Clocks
    (1.41 -> 0.59s) and RUINED DM DOKURO (0.21 -> 0.69s), so a chooser that
    cannot decline it would be trading one failure for another.
    """
    import local_align as LA
    import torch

    device = device if torch.cuda.is_available() else "cpu"
    net, rest = M.load(ckpt, device)
    calibration = float(rest.get("calibration") or 0.0)
    doc = lyric(tid, any_source=any_source)
    rows = _groups(doc)
    if not rows:
        raise SystemExit("that lyric has no words in it")
    log(f"{sum(len(r['words']) for r in rows)} words to place "
        f"({net.size()}, step {rest.get('step', '?')})")

    with LA.fetched(f"{meta['artist']} {meta['title']}",
                    float(meta.get("length") or 0), artist=meta.get("artist", ""),
                    tid=tid) as path:
        if not path:
            raise SystemExit(f"no copy could be fetched — {LA.fetched.last_error}")
        wave, rate = audio.read(path)
        mono = audio.mono16k(wave, rate)
        heard: dict = {}

        # WHICH RECORDING THIS FILE IS FOR. The copy is fetched from YouTube and
        # the file is played against Spotify, and those are not always the same
        # master: Krantenwijk aligned against a copy 2.22s shorter than the
        # track it will be played over. The fetcher already prefers the closest
        # duration it can find -- this is not a ranking mistake, it is the best
        # copy there was -- but nothing ever said so out loud, and a listener
        # hearing the file drift has no way to tell a model error from a
        # different edit. So it is said.
        want = float(meta.get("length") or 0)
        apart = (mono.shape[-1] / audio.RATE) - want if want else 0.0
        if abs(apart) > 0.5:
            log(f"CAREFUL: the copy fetched is {abs(apart):.2f}s "
                f"{'shorter' if apart < 0 else 'longer'} than the track you "
                f"will play this over — it may be a different edit, and times "
                f"from it can be right about the audio and wrong about yours")

        # The automatic offset, before anything is aligned: a copy with silence
        # bolted on the front would otherwise put every word in the file late
        # by that much, and nothing downstream would ever notice.
        lag, why = offset.trim(mono, float(meta.get("length") or 0))
        if why:
            log(why)
        if lag:
            mono = mono[int(lag * audio.RATE):]

        def separated():
            log("separating the vocal")
            dev, win, _ = LA.room("gpu", LA.DEMUCS_COST, LA.DEMUCS_WINDOW, spare)
            # Recorded because it changes the answer: the same song separated
            # over a 2s window and a 7.8s one gives different vocals, and so
            # different times. Two runs of this command are only the same run
            # if this number matches.
            heard["window"] = round(win, 1)
            sep, srate = LA.separate(wave, rate, dev, win, LA.MODEL, None, None)
            out = audio.mono16k(sep, srate)
            LA.release()
            return out[int(lag * audio.RATE):] if lag else out

        if stem:
            mono = separated()

        log(f"listening to {mono.shape[-1] / audio.RATE:.0f}s of audio")
        logp, boundary = M.emit(net, mono, device, return_boundary=True)
        if not getattr(net, "has_boundary", True):
            log("this checkpoint predates the boundary head -- word ends come "
                "from the letters alone")
            boundary = None
        # What the audio says about where the singing is. Measured from the
        # very waveform the model was given, so with --stem this reads the
        # separated vocal, where a quiet frame means nobody is singing rather
        # than nobody is loud. Defaults live in GATE/ATTACK above.
        want_gate = GATE if gate is None else gate
        reach = SUSTAIN if sustain is None else sustain
        want_attack = ATTACK if attack is None else attack
        present = onset = None
        if want_gate > 0 or want_attack > 0:
            from . import vocal
            if want_gate > 0:
                present = vocal.activity(mono, logp.shape[0])
            if want_attack > 0:
                onset = vocal.onsets(mono, logp.shape[0])
        rows = _timed(rows, logp, device, lag=-calibration, log=log,
                      boundary=boundary, present=present, onset=onset,
                      gate=want_gate, attack=want_attack, sustain=reach)
        heard.update(seconds=round(mono.shape[-1] / audio.RATE, 2),
                     track=want, apart=round(apart, 2))

        # AUTO: the mixture was tried; separate only if it went badly. Doing it
        # this way round means a song the model already hears well never pays
        # for demucs, and a song it does not gets the one thing measured to
        # help it most.
        if stem is None:
            sure = confidence(rows)
            spare_ckpt = fallback or _sibling(ckpt)
            if sure >= WEAK:
                log(f"the mixture reads clearly ({sure:.2f}) -- not separating")
            elif spare_ckpt is None:
                log(f"the mixture reads poorly ({sure:.2f}), and there is no "
                    f"stem-trained model beside {pathlib.Path(ckpt).name} "
                    f"to fall back to")
            else:
                log(f"the mixture reads poorly ({sure:.2f}) -- separating and "
                    f"trying again with {pathlib.Path(spare_ckpt).name}")
                mono = separated()
                net, rest = M.load(spare_ckpt, device)
                calibration = float(rest.get("calibration") or 0.0)
                logp, boundary = M.emit(net, mono, device, return_boundary=True)
                if not getattr(net, "has_boundary", True):
                    boundary = None
                present = onset = None
                if want_gate > 0 or want_attack > 0:
                    from . import vocal
                    if want_gate > 0:
                        present = vocal.activity(mono, logp.shape[0])
                    if want_attack > 0:
                        onset = vocal.onsets(mono, logp.shape[0])
                again = _timed(_groups(doc), logp, device, lag=-calibration,
                               log=log, boundary=boundary, present=present,
                               onset=onset, gate=want_gate, attack=want_attack)
                now = confidence(again)
                # Only if it actually helped. Separation is not a free win --
                # it made DM DOKURO three times worse -- so the mixture keeps
                # the song unless the stems genuinely read better.
                if now > sure:
                    log(f"the separated vocal reads better ({now:.2f}) -- "
                        f"keeping it")
                    rows = again
                else:
                    log(f"the separated vocal is no better ({now:.2f}) -- "
                        f"keeping the mixture")

        # Only the lines that were squeezed, and only if asked. See _uncrush:
        # the same floor applied to the whole song is measurably worse.
        if uncrush:
            n = _uncrush(rows, logp, device, boundary=boundary, present=present,
                         onset=onset, gate=want_gate, attack=want_attack,
                         log=log)
            if n:
                log(f"{n} squeezed line(s) re-timed")

        # What the words themselves say they need. See _repace: this is the
        # only stage that knows a line can be given TOO MUCH room.
        if repace:
            n = _repace(rows, logp, device, boundary=boundary, present=present,
                        onset=onset, gate=want_gate, attack=want_attack,
                        log=log)
            if n:
                log(f"{n} over-long line(s) started again")

        # One edge, moved onto the loudest attack the line could begin on.
        if onattack:
            n = _onattack(rows, logp, device, boundary=boundary,
                          present=present, onset=onset, gate=want_gate,
                          attack=want_attack, log=log)
            if n:
                log(f"{n} line(s) moved onto a stronger attack")

        # THIS SONG'S OWN BIAS, measured against its own attacks rather than
        # against anybody's lyric. The global calibration is one number for
        # every song, and songs disagree: three Dutch files read 0.118-0.176s
        # ahead of their reference and a fourth 0.192s behind it. A sung attack
        # is a fact about the recording, so the gap between a word and the
        # attack it was placed on can be measured with no reference at all --
        # and in any language.
        if onset is not None and lean:
            starts = sorted(w["start"] for r in rows for w in r["timed"]
                            if w.get("start") is not None)
            found = vocal.drift(starts, onset)
            if found["trusted"] and abs(found["lag"]) > 0.02:
                move = max(-LEAN, min(LEAN, found["lag"]))
                log(f"this file sits {found['lag']:+.3f}s from its own sung "
                    f"attacks ({found['pairs']} words, spread "
                    f"{found['spread']:.3f}) -- taking {move:+.3f}s off")
                for r in rows:
                    for w in r["timed"]:
                        if w.get("start") is None:
                            continue
                        w["start"] -= move
                        w["end"] -= move
                        w["chars"] = [(a - move, b - move) for a, b in w["chars"]]
            elif found["pairs"]:
                log(f"no clear bias against its own attacks ({found['why']})")

    placed = sum(1 for r in rows for w in r["timed"] if w.get("start") is not None)
    total = sum(len(r["words"]) for r in rows)
    log(f"{placed} of {total} words placed")
    got = document(doc, rows)
    got["_placed"] = [placed, total]
    # What this file was timed against, kept in the file itself: a reader
    # wondering why a line sits where it does can see whether the copy even
    # matched the track they are playing.
    got["TimedAgainst"] = heard
    return got
