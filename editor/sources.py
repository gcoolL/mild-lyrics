"""Where the words and credits come from: Genius for the text, the Mild Lyrics
chain for timed documents, Genius and Apple for songwriters. No GUI."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path[:0] = [str(p) for p in (_ROOT / "mild-lyrics", _ROOT)
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
    """Songs Genius thinks this might be, best first, translations dropped.
    Raises when Genius could not be asked; [] when it was asked and knows no
    such song."""
    out = []
    hits = LA._genius_hits(token, title, artist, timeout) or []
    if not hits and LA._genius_hits.last_error:
        raise RuntimeError(LA._genius_hits.last_error)
    for hit in hits:
        got = hit.get("result") if isinstance(hit.get("result"), dict) else hit
        if not GR.is_song(hit) or GR.is_romanisation(hit):
            continue
        if not got.get("id"):
            continue
        out.append({"id": got["id"],
                    "title": got.get("full_title") or got.get("title") or "",
                    "artist": ((got.get("primary_artist") or {}).get("name") or ""),
                    "url": got.get("url") or ""})
    return out


def genius_doc(token: str, song_id: int, timeout: float = 8.0) -> M.Doc | None:
    """One Genius song as an untimed document with its voices and ad-libs read
    from the markup. Raises when the page could not be read."""
    try:
        raw = GR.lyrics_for(int(song_id), timeout, markup=True)
    except Exception as exc:                             # noqa: BLE001
        raise RuntimeError(GR.why(exc, timeout)) from exc
    if not raw or not raw.strip():
        if GR.lyrics_for.last_error:
            raise RuntimeError(GR.lyrics_for.last_error)
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
        if not ln.lead.syls and ln.bg and lines:
            # An ad-lib on a row of its own answers the line above it, the
            # way the text tab reads one (M.from_text).
            M.under(lines[-1], ln.bg)
            continue
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
        try:
            hits = genius_hits(token, title, artist, timeout)
        except Exception:                                # noqa: BLE001
            return {}
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
    """Apple's composer credit for this song, split into a list of names."""
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
    """Apple's credits for this song, by role. Performing names, not legal
    ones."""
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
    """Apple's writer credits (from the publishing, so legal names where there
    are some) and where they came from."""
    got = apple_credits(str(meta.get("title") or ""),
                        str(meta.get("artist") or ""))
    names = got.get("songwriters") or []
    if names:
        return names, "Apple Music's credits"
    flat = apple_songwriters(str(meta.get("title") or ""),
                             str(meta.get("artist") or ""))
    return (flat, "Apple Music") if flat else ([], "")


def songwriters(meta: dict, token: str = "", song_id: int | None = None) -> tuple[list, str]:
    """Who wrote this song and who says so: Genius first, then Apple; never
    merged."""
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
    """Which providers the player asks, and in what order, read from its
    settings and expanded from sources to providers as the player does."""
    cfg = L.load_settings()
    LS.set_bases(n for n, k in LS.BASE_KEY.items()
                 if cfg.get(k, L.DEFAULTS.get(k, True)))
    # Settings ▸ Sources ▸ Syncs, as the player hands them to the chain.
    split = lambda key: [n.strip() for n in str(cfg.get(key) or "").split(",") if n.strip()]
    LS.set_syncs(split("sync_off"), split("sync_order"))
    raw = str(cfg.get("src_order") or L.DEFAULTS.get("src_order") or "")
    order = [n.strip() for n in raw.split(",") if n.strip() in LS.SOURCES]
    order += [n for n in LS.SOURCES if n not in order]
    got = LS.provider_order(
        order,
        lambda n: bool(cfg.get(f"src_{n}", L.DEFAULTS.get(f"src_{n}", False))),
        lambda b: bool(cfg.get(LS.BLEND_KEY[b],
                               L.DEFAULTS.get(LS.BLEND_KEY[b], True))))
    got = [n for n in got if n not in NOT_HERE]
    return got, set(got)


# Never fetched into the editor: Spicy Lyrics' syncs are for showing.
NOT_HERE = ("spicy",)


# The player's "bini" is two doors (lrc.red, then BiniLyrics), and the two can
# hand back different syncs for one ISRC. Here each is asked on its own.
DOORS = {"lrc.red": "from_lrcred", "BiniLyrics": "from_bini"}


def with_doors(names) -> list[str]:
    """`names` with "bini" opened up into its two doors."""
    return [d for n in names for d in (DOORS if n == "bini" else (n,))]


def providers() -> list[str]:
    """Every source that can be asked for by name."""
    return with_doors(n for n, _fn in LS.PROVIDERS if n not in NOT_HERE)


def _one_door(tid: str, meta: dict, door: str, note=None):
    """One of Apple Music's doors and nothing else, as the walk's answer shape."""
    faults: dict = {}
    try:
        body = LS._under(None, lambda: getattr(LS, DOORS[door])(tid, meta),
                         faults, door)
    except Exception as exc:                            # noqa: BLE001
        raise RuntimeError(f"{door}: {type(exc).__name__}: {exc}") from exc
    finally:
        if note is not None and faults:
            note(sorted(faults.items()))
    return None if not body or LS.wordless(body) else (body, door)


def player_people() -> LS.Roster:
    """Whose syncs the player refuses and whose it prefers, from its settings."""
    cfg = L.load_settings()
    return LS.Roster(cfg.get("people_skip") or "", cfg.get("people_pick") or "")


def chain_doc(tid: str, meta: dict, order=None, only: str = "",
              note=None) -> tuple[M.Doc | None, str]:
    """The best document Mild Lyrics can find for this track, and its source.
    `force` skips the cache, `only` names one provider, `note` hears
    unreachable sources."""
    if only in NOT_HERE:
        raise RuntimeError("Spicy Lyrics is not fetched into the editor")
    if only:
        want, enabled = [only], {only}
    else:
        want, enabled = player_sources()
        if order:
            want = [n for n in order if n not in NOT_HERE]
    if only in DOORS:
        got = _one_door(tid or "", meta, only, note)
    else:
        try:
            got = LS.fallback(tid or "", meta, "none", enabled=enabled,
                              force=True, order=want,
                              people=None if only else player_people(), note=note)
        except Exception as exc:                        # noqa: BLE001
            raise RuntimeError(f"{', '.join(want) or 'the chain'}: "
                               f"{type(exc).__name__}: {exc}") from exc
    if not got:
        return None, ""
    body = got[0] if isinstance(got, tuple) else got
    name = ""
    if isinstance(got, tuple) and len(got) > 1:
        name = str(got[1] or "")
    if LS.spicy_made(body):
        body = LS.apple_instead(tid or "", meta)
        if not body:
            raise RuntimeError("a Spicy Lyrics sync is not fetched here, and "
                               "Apple Music has none for this song")
        name = "Apple Music, in place of a Spicy Lyrics sync"
    doc = SL.payload(body)
    name = name or str(doc.get("_source") or doc.get("source") or "")
    out = M.from_body(body)
    _borrow_duet(out, body, tid, meta)
    return out, name


def _borrow_duet(doc: M.Doc, body, tid: str, meta: dict) -> bool:
    """Fill in the second voice from amll-ttml-db, as the player does, only
    where the source flagged no voice at all."""
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
    """Find the ad-libs from the text alone: whole bracketed lines, trailing
    brackets; lines with a backing group left alone. `alternate` is ignored."""
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
    """A stable filename for a song with no track id: a slug of the names plus
    a hash."""
    import hashlib
    import re
    raw = f"{artist.strip().lower()} - {title.strip().lower()}"
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:60] or "song"
    return f"{slug}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"


def fetch_audio(title: str, artist: str = "", length: float = 0.0,
                tid: str = "", words: list[str] | None = None,
                say=None) -> tuple[str, str]:
    """A copy of this song on disk to time against, via `local_align.fetched`;
    kept, in the player's store. Returns (path, warning); raises
    RuntimeError."""
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
        if LA.fetched.url:
            # Which upload this is, so a multiplayer host can point the
            # others at the very same one (see source_of).
            LS.pin_source(key, LA.fetched.url)
        return str(kept), warn


def audio_hits(title: str, artist: str = "", length: float = 0.0) -> list[dict]:
    """Every recording the search turned up, for somebody to choose from, in
    fetch_audio's order; Go+ copies counted in `audio_hits.gated`."""
    query = " ".join(x for x in (artist.strip(), title.strip()) if x)
    if not query:
        raise RuntimeError("name the song first — there is nothing to search "
                           "for")
    ranked = LA.find(query, float(length or 0.0), artist=artist, title=title)
    order = {url: n for n, (url, _dur) in enumerate(ranked)}
    rows = list(LA.find.all)
    rows.sort(key=lambda r: (order.get(r["url"], len(order)), r["gap"]))
    audio_hits.gated = list(LA.find.gated)
    if not rows:
        raise RuntimeError(LA.why_none(float(length or 0.0)))
    return rows


audio_hits.gated = []


def source_of(title: str, artist: str = "", tid: str = "") -> str:
    """The upload a kept copy of this song was downloaded from, or ''."""
    return LS.pinned_source(tid or audio_key(artist, title))


def kept_source(path) -> str:
    """The upload a file in the kept-copies store came from, or '' for any
    file that is not one of those."""
    try:
        f = pathlib.Path(path).resolve()
        if f.parent != LA.AUDIO_DIR.resolve():
            return ""
    except (OSError, ValueError):
        return ""
    return LS.pinned_source(f.stem)


def fetch_audio_url(url: str, title: str, artist: str = "",
                    tid: str = "") -> str:
    """Download this one recording and keep it, the way fetch_audio does."""
    import tempfile
    key = tid or audio_key(artist, title)
    tmp = str(pathlib.Path(tempfile.gettempdir())
              / f"mild-editor-{os.getpid()}.wav")
    try:
        got = LA.fetch(url, tmp)
        if not got:
            raise RuntimeError(LA.fetch.last_error or "download failed")
        LS.pin_source(key, url)
        LA._keep(key, got)
        kept = LA._kept(key)
        if kept is None:
            raise RuntimeError(f"downloaded it, but could not keep a copy in "
                               f"{LA.AUDIO_DIR}")
        return str(kept)
    finally:
        stem = tmp.rsplit(".", 1)[0]
        for leftover in (tmp, stem + ".webm", stem + ".m4a",
                         stem + ".mp3", stem + ".opus"):
            try:
                os.remove(leftover)
            except OSError:
                pass
