"""Where the words and the credits come from.

Three suppliers, each asked for the thing it is actually good at:

  * Genius for the TEXT. It is edited by people who are listening to the
    song, it marks who sings what in its section headers and its typography,
    and it is the only one of the three that knows an ad-lib is an ad-lib.
  * the Mild Lyrics chain for a document somebody has already timed --
    amll-ttml-db, LRCLIB, NetEase, QQ and the rest, exactly as the player
    ranks them. That is the right starting point when the job is to fix a
    sync rather than to make one.
  * Genius and Apple Music for the SONGWRITERS, which neither the words nor
    the timings carry.

Nothing here touches the GUI, and every call returns something ordinary --
a Doc, a list of names, or None -- so the window can run all of it on a
worker thread.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path[:0] = [str(p) for p in (_ROOT / "aligner", _ROOT)
                if str(p) not in sys.path]

import genius_roman as GR       # noqa: E402
import lyric_sources as LS      # noqa: E402
import lyrics_gui as L          # noqa: E402
import local_align as LA        # noqa: E402
import spicy_lyrics as SL       # noqa: E402

from . import model as M        # noqa: E402

CACHE = L.app_dir("cache")


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def genius_hits(token: str, title: str, artist: str, timeout: float = 8.0) -> list[dict]:
    """Songs Genius thinks this might be, best first, translations dropped."""
    out = []
    for hit in LA._genius_hits(token, title, artist, timeout) or []:
        got = hit.get("result") if isinstance(hit.get("result"), dict) else hit
        if not GR.is_song(hit) or GR.is_romanization(hit):
            continue
        if not got.get("id"):
            continue
        out.append({"id": got["id"],
                    "title": got.get("full_title") or got.get("title") or "",
                    "artist": ((got.get("primary_artist") or {}).get("name") or ""),
                    "url": got.get("url") or ""})
    return out


def genius_doc(token: str, song_id: int, timeout: float = 8.0) -> M.Doc | None:
    """One Genius song as an untimed document, voices and ad-libs and all.

    Genius' own markup is read rather than thrown away: its section headers
    name who sings each part, its typography marks which of them is singing
    each line, and a trailing parenthesis is an ad-lib. That is precisely the
    three things a TTML needs and nothing else here can infer -- so a document
    fetched this way arrives with its duet sides and its backing vocals
    already set, and the editor's job is to check them rather than to make
    them.
    """
    try:
        raw = GR.lyrics_for(int(song_id), timeout, markup=True)
    except Exception:
        return None
    if not raw or not raw.strip():
        return None
    rows = GR.voiced_lines(raw)
    if not rows:
        return None
    second = GR.sides(rows)
    lines = []
    for row, other in zip(rows, second):
        lead, head, bgs = M._peel_backing(row["text"])
        ln = M.Line(M.Group([M.Syl(w) for w in M.words_in(lead)]),
                    [M.Group([M.Syl(w) for w in M.words_in(b)], lead_in=True)
                     for b in head]
                    + [M.Group([M.Syl(w) for w in M.words_in(b)]) for b in bgs],
                    "v2" if other else "v1")
        if not ln.lead.syls and ln.bg:
            ln.lead, ln.bg = ln.bg[0], ln.bg[1:]
        if ln.lead.syls:
            lines.append(ln)
    if not lines:
        return None
    doc = M.Doc(lines)
    doc.meta["source"] = "genius"
    return doc


def genius_credits(token: str, title: str, artist: str,
                   song_id: int | None = None, timeout: float = 8.0) -> dict:
    """Songwriters and producers, from Genius' own credits for the song."""
    if song_id is None:
        hits = genius_hits(token, title, artist, timeout)
        if not hits:
            return {}
        song_id = hits[0]["id"]
    try:
        raw = GR._get(f"{GR.API}/songs/{song_id}",
                      {"Authorization": "Bearer " + token}, timeout)
        song = (json.loads(raw) or {}).get("response", {}).get("song") or {}
    except Exception:
        return {}
    names = lambda key: [str((a or {}).get("name") or "").strip()          # noqa: E731
                         for a in (song.get(key) or [])
                         if (a or {}).get("name")]
    return {"id": song_id,
            "title": song.get("full_title") or "",
            "writers": names("writer_artists"),
            "producers": names("producer_artists"),
            "url": song.get("url") or ""}


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
_apple_token = LS._apple_token
_apple_get = LS._amp


def apple_songwriters(title: str, artist: str) -> list[str]:
    """Apple's composer credit for this song, as a list of names.

    Apple writes them as one string -- "Chris Martin, Guy Berryman, Jonny
    Buckland & Will Champion" -- so it is split back apart here, which is the
    shape TTML wants (one <songwriter> each) and the shape Genius already
    hands over.
    """
    token = _apple_token()
    if not token:
        return []
    q = urllib.parse.urlencode({"term": f"{artist} {title}".strip(),
                                "types": "songs", "limit": 5})
    got = _apple_get(token, f"search?{q}")
    if got is None:
        got = _apple_get(_apple_token(force=True), f"search?{q}")
    data = (((got or {}).get("results") or {}).get("songs") or {}).get("data") or []
    want_t, want_a = L._akey(title), L._akey(artist)
    for song in data:
        at = song.get("attributes") or {}
        if want_t and want_t not in L._akey(at.get("name") or ""):
            continue
        if want_a and not (want_a in L._akey(at.get("artistName") or "")
                           or L._akey(at.get("artistName") or "") in want_a):
            continue
        who = str(at.get("composerName") or "").strip()
        if who:
            return _split_names(who)
    return []


WROTE_IT = ("composition", "lyrics", "writing")
WROTE = ("composer", "lyricist", "lyrics", "writer", "songwriter")


def apple_credits(title: str, artist: str) -> dict:
    """Apple's credits for this song, by the role each person is under.

    Richer than `composerName`, which is one flat string with everybody in
    it: this keeps the roles Apple files them under, so the people who WROTE
    the song can be told from the people who produced or engineered it.

    Not legal names, though. Apple's credits carry the same performing names
    Genius does -- Love Blur's writers come back "slayr" and "waera .", not
    the names on the publishing. Nothing reachable from here carries those:
    MusicBrainz models a legal name as a relationship and does not have one
    for most artists, and the PRO repertories (ASCAP, BMI) refuse machine
    access outright. So this is offered for what it is.
    """
    token = _apple_token()
    if not token:
        return {}
    q = urllib.parse.urlencode({"term": f"{artist} {title}".strip(),
                                "types": "songs", "limit": 5})
    got = _apple_get(token, f"search?{q}")
    if got is None:
        got = _apple_get(_apple_token(force=True), f"search?{q}")
    data = (((got or {}).get("results") or {}).get("songs") or {}).get("data") or []
    want_t, want_a = L._akey(title), L._akey(artist)
    for song in data:
        at = song.get("attributes") or {}
        if want_t and want_t not in L._akey(at.get("name") or ""):
            continue
        if want_a and not (want_a in L._akey(at.get("artistName") or "")
                           or L._akey(at.get("artistName") or "") in want_a):
            continue
        full = _apple_get(token, f"songs/{song.get('id')}?include=credits")
        rel = (((full or {}).get("data") or [{}])[0].get("relationships")
               or {}).get("credits") or {}
        wrote, made, seen = [], [], set()
        for group in rel.get("data") or []:
            head = str((group.get("attributes") or {}).get("title") or "").lower()
            people = ((group.get("relationships") or {}).get("credit-artists")
                      or {}).get("data") or []
            for who in people:
                gat = who.get("attributes") or {}
                name = str(gat.get("name") or "").strip()
                roles = [str(r).lower() for r in (gat.get("roleNames") or [])]
                if not name:
                    continue
                writer = (any(any(w in r for w in WROTE) for r in roles)
                          if roles else any(k in head for k in WROTE_IT))
                bucket = wrote if writer else made
                if writer and name.lower() in seen:
                    continue
                if writer:
                    seen.add(name.lower())
                bucket.append(name)
        if wrote or made:
            return {"songwriters": wrote, "others": made,
                    "composer": str(at.get("composerName") or "")}
    return {}


_split_names = LS.apple_names


def apple_writers(meta: dict) -> tuple[list, str]:
    """Apple's writer credits for this song, and where they came from.

    Kept apart from songwriters() because it answers a different question.
    Genius lists who its editors credit; Apple lists what the publishing
    says, which is where a legal name appears when there is one -- luther
    comes back with "Roshwita Larisha Bacha" and "Mark Anthony Spears" where
    Genius has "Ink" and "Sounwave". On a self-released track the publishing
    is the artist's own name and both say the same thing.
    """
    got = apple_credits(str(meta.get("title") or ""),
                        str(meta.get("artist") or ""))
    names = got.get("songwriters") or []
    if names:
        return names, "Apple Music's credits"
    flat = apple_songwriters(str(meta.get("title") or ""),
                             str(meta.get("artist") or ""))
    return (flat, "Apple Music") if flat else ([], "")


def songwriters(meta: dict, token: str = "", song_id: int | None = None) -> tuple[list, str]:
    """Who wrote this song, and who says so.

    Genius first because it separates writers from producers and Apple does
    not, and Apple second because it carries songs Genius has never had a
    page for. Whichever answers is the answer; they are not merged, since two
    databases spelling the same four people differently would put eight names
    in the file.
    """
    title = str(meta.get("title") or "")
    artist = str(meta.get("artist") or "")
    if token:
        got = genius_credits(token, title, artist, song_id)
        if got.get("writers"):
            return got["writers"], "Genius"
    got = apple_songwriters(title, artist)
    if got:
        return got, "Apple Music"
    return [], ""


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def player_sources() -> tuple[list, set]:
    """Which providers the player asks, and in what order.

    Read from its settings rather than assumed. Asking the chain with no
    preferences at all walks lyric_sources.PROVIDERS with everything switched
    on -- which is not what the player does, and on gc's machine meant the
    editor answering with a blend (which he had switched OFF, and which merges
    Apple's TTML in) where the player would have answered with the community
    db.

    The player's settings are a list of SOURCES and the chain wants providers,
    so the same expansion the player does is done here -- otherwise the two
    disagree about who is even being asked.
    """
    cfg = L.load_settings()
    raw = str(cfg.get("src_order") or L.DEFAULTS.get("src_order") or "")
    order = [n.strip() for n in raw.split(",") if n.strip() in LS.SOURCES]
    order += [n for n in LS.SOURCES if n not in order]
    got = LS.provider_order(
        order,
        lambda n: bool(cfg.get(f"src_{n}", L.DEFAULTS.get(f"src_{n}", False))),
        lambda b: bool(cfg.get(LS.BLEND_KEY[b],
                               L.DEFAULTS.get(LS.BLEND_KEY[b], True))))
    return got, set(got)


def providers() -> list[str]:
    """Every source that can be asked for by name."""
    return [n for n, _fn in LS.PROVIDERS]


def player_people() -> LS.Roster:
    """Whose syncs the player refuses, and whose it prefers.

    Read from its settings for the same reason player_sources is: the editor
    fetching a starting point wants the document the player would have put on
    screen, and a contributor the user has said no to is no more wanted here
    -- fixing somebody's sync is not a way to be handed it.
    """
    cfg = L.load_settings()
    return LS.Roster(cfg.get("people_skip") or "", cfg.get("people_pick") or "")


def chain_doc(tid: str, meta: dict, order=None, only: str = "",
              note=None) -> tuple[M.Doc | None, str]:
    """The best document Mild Lyrics can find for this track, and its source.

    `force` because the editor is asking on purpose: the chain caches its
    answer for the player's benefit, and a user pressing "fetch" wants the
    lookup done, not the last one repeated.

    `only` asks one named provider and nothing else -- for when the chain's
    ranking is not the question and a particular source is.

    `note` is handed the sources that could not be reached, the same way the
    player's walk hands them over. A door being down and a song not being
    behind it read identically here -- "had nothing for it" -- and asking one
    named source is exactly where the difference matters.
    """
    if only:
        want, enabled = [only], {only}
    else:
        want, enabled = player_sources()
        if order:
            want = list(order)
    try:
        got = LS.fallback(tid or "", meta, "none", enabled=enabled,
                          force=True, order=want,
                          people=None if only else player_people(), note=note)
    except Exception as exc:                            # noqa: BLE001
        raise RuntimeError(f"{', '.join(want) or 'the chain'}: "
                           f"{type(exc).__name__}: {exc}") from exc
    if not got:
        return None, ""
    body = got[0] if isinstance(got, tuple) else got
    name = ""
    if isinstance(got, tuple) and len(got) > 1:
        name = str(got[1] or "")
    doc = SL.payload(body)
    name = name or str(doc.get("_source") or doc.get("source") or "")
    out = M.from_body(body)
    _borrow_duet(out, body, tid, meta)
    return out, name


def _borrow_duet(doc: M.Doc, body, tid: str, meta: dict) -> bool:
    """Fill in the second voice from amll-ttml-db, where the source had none.

    Most providers do not carry the flag at all -- LRCLIB and QQ have nowhere
    to put it, and a good share of Spicy Lyrics' own entries are duets with it
    never set. amll keeps the TTML agents, so it is the one place to ask. The
    player already does this and caches the answer; this is the same call, so
    a document fetched here comes out marked up the same way the player would
    have marked it.

    Only where nothing is flagged already: overwriting a source that DID say
    who sings what with somebody else's reading trades one answer for another.
    """
    if any(ln.agent != "v1" for ln in doc.lines):
        return False
    try:
        rows = SL.timeline(body)
        flags = LS.duet_flags(rows, tid, meta or {})
    except Exception:
        return False
    if not flags or len(flags) != len(rows):
        return False
    lead = [f for f, row in zip(flags, rows) if not row.get("background")]
    if len(lead) != len(doc.lines):
        return False
    hit = 0
    for ln, other in zip(doc.lines, lead):
        if other:
            ln.agent, hit = "v2", hit + 1
    return bool(hit)


def quality(doc: M.Doc) -> str:
    """What this document is: word-synced, line-synced, or just words."""
    if any(s.timed for ln in doc.lines for g in ln.groups() for s in g.syls):
        return "word"
    if any(ln.start is not None for ln in doc.lines):
        return "line"
    return "none"


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def detect_roles(doc: M.Doc, alternate: bool = False) -> str:
    """Find the ad-libs from the text alone.

    Only the shapes that are conventions rather than guesses:

      * a whole line inside brackets is a backing line;
      * a trailing bracketed run is an ad-lib answering the line it follows;
      * a line ALREADY carrying a backing group is left alone.

    `alternate` used to stripe every other line onto the second voice. It is
    gone: striping is a convention applied to a song nobody has read, it says
    nothing true about who sings what, and on a lyric that already had its
    sides marked it threw that reading away. What the button does now is
    ops.swap_agents, which mirrors the reading instead of replacing it. The
    argument is still accepted so old callers do not break, and ignored.
    """
    moved = 0
    for ln in doc.lines:
        if ln.bg:
            continue
        lead, head, tail = M._peel_backing(ln.lead.text())
        if not (head or tail):
            continue
        run = ln.lead.words()
        want = ([(b, True) for b in head] + [(lead, None)]
                + [(b, False) for b in tail])
        counts = [len(M.words_in(text)) for text, _ in want]
        if sum(counts) != len(run):
            continue
        syls, at, made, keep = ln.lead.syls, 0, [], []
        for (text, before), n in zip(want, counts):
            idx = [i for w in run[at:at + n] for i in w]
            at += n
            if before is None:
                keep = idx
                continue
            if not idx:
                continue
            g = M.Group([syls[i] for i in idx], lead_in=bool(before))
            g.syls[0].text = g.syls[0].text.lstrip("([（")
            g.syls[-1].text = g.syls[-1].text.rstrip(")]）")
            g.syls[-1].part = False
            made.append(g)
        if not keep or not made:
            continue
        ln.lead = M.Group([syls[i] for i in keep])
        ln.lead.syls[-1].part = False
        ln.bg.extend(made)
        moved += len(made)
    return f"{moved} ad-lib(s) found" if moved else "no bracketed ad-libs"


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def audio_key(artist: str, title: str) -> str:
    """A stable filename for a song that has no track id of its own.

    The player keys its kept copies by Spotify id, which is the right key
    when there is one and no key at all when the words came from Genius or a
    file. A slug of the two names is the next best thing: it is stable across
    sessions, so the second time somebody asks for a song they get the copy
    instead of the download, and the hash on the end keeps two songs whose
    names slugify the same from overwriting each other.
    """
    import hashlib
    import re
    raw = f"{artist.strip().lower()} - {title.strip().lower()}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:60] or "song"
    return f"{slug}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"


def fetch_audio(title: str, artist: str = "", length: float = 0.0,
                tid: str = "", words: list[str] | None = None,
                say=None) -> tuple[str, str]:
    """A copy of this song on disk to time against. Returns (path, warning).

    The editor has always been able to fetch the WORDS and never the song
    they belong to, which left one job -- find a recording -- as the only
    thing somebody had to leave the program to do. Worse, it left them doing
    it by hand, and a hand-found file is how a 212-second recording came to
    be open behind a 103-second lyric with nothing saying so.

    `local_align.fetched` is the player's own fetcher and it does the part
    that matters: it searches by name AND length, and then plays the
    candidate to a speech model to check the words it hears are this song's
    words, against a handful of other songs as decoys. A recording of the
    wrong song at the right length is the failure this catches and a length
    check alone cannot. Pass `words` -- from the document that is open -- and
    that check runs; leave it out and it cannot.

    The copy is KEPT, unlike the player's use of the same call, where it is
    deleted the moment the alignment finishes. An editor holds a song open
    for an afternoon, and re-downloading it every time the window opens would
    be both slow and rude to whoever is hosting it. It lands in the same
    store the player fills, under the same 8 GB cap, so `caches.py` can see
    it and the Storage dialog can clear it.

    Raises RuntimeError with `fetched`'s own words when there is no copy to
    be had -- those explain three quite different failures and are worth
    passing through unedited.
    """
    import shutil
    tell = say or (lambda _m: None)
    key = tid or audio_key(artist, title)
    got = LA._kept(key)
    if got:
        tell("using the copy kept from last time")
        return str(got), ""
    query = " ".join(x for x in (artist.strip(), title.strip()) if x)
    if not query:
        raise RuntimeError("name the song first — there is nothing to search "
                           "for")
    with LA.fetched(query, float(length or 0.0), artist=artist, tid=tid,
                    words=words or None, say=tell) as path:
        if not path:
            raise RuntimeError(LA.fetched.last_error
                               or "no copy could be found")
        warn = ""
        if LA.fetched.unverified:
            url, why = LA.fetched.unverified
            warn = f"{LA._named(url)} was not checked — {why}"
        if LA.fetched.doubted is not None:
            warn = (f"every copy failed the word check; this was the closest "
                    f"({LA.fetched.doubted * 100:+.0f}%) — listen before "
                    f"trusting it")
        kept = LA._kept(key)
        if kept is None:
            LA._keep(key, path)
            kept = LA._kept(key)
        if kept is None:
            raise RuntimeError(f"downloaded it, but could not keep a copy in "
                               f"{LA.AUDIO_DIR}")
        return str(kept), warn
