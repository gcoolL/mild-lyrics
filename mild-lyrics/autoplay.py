"""What Mild Lyrics' own player plays after its queue: `fuse` merges the
sources' radios by rank, `pick` makes a varied run of them. Notes:
docs/notes/mild-lyrics/home_page.md."""
from __future__ import annotations

import random
import re
import unicodedata

AHEAD = 25            # autoplay songs kept queued ahead
TOP_UP_BELOW = 10     # ...topped up when fewer than this are left
PER_ARTIST = 2        # most songs by one artist in a top-up
SEED_SHARE = 5        # the seed's own artist at most once in this many
SEED_HOPS = 1         # a heard autoplay song seeds only if it came from the anchor's own lists (2026-10-25)
RRF_K = 8             # rank fusion's k: small, so a list's 1st and 20th still differ
FUSED = 100.0         # a fused score to pick's points: a list's 1st is 12.5, its 20th 3.6
SKIP_STEP = 3.0       # points off an artist per autoplay skip this session
SKIPS_OUT = 2         # ...and left out after this many
LIKED_REST = 20       # a liked song may come back once this many plays have passed
DROP_FREE = 2.0       # dB quieter than the song before that costs nothing (skips measured 2026-10-24)
DROP_STEP = 6.0       # places a song moves back per dB quieter beyond that (replayed 2026-10-24)
SMOOTH_SPAN = 6       # ...choosing among this many songs ahead at most
AGREE_MIN = 5         # a song radio with fewer rows by the anchor artist's Deezer radio's artists is another audience's
AGREE_ROWS = 20       # ...judged only when both lists are this long (12-25 of 49 on seven anchors, Trolls' cut 1; 2026-10-27)
STRAY_W = 0.25        # such a radio's weight in fusion


def stray(radio: list[dict], artist_radio: list[dict]) -> bool:
    """Whether a song radio is another audience than the artist's: the Art Track of "CAN'T STOP THE
    FEELING!" is the Trolls cut, and its radio was kids' songs while its music video's was pop."""
    if len(radio) < AGREE_ROWS or len(artist_radio) < AGREE_ROWS:
        return False
    theirs = {artist_of(t) for t in artist_radio}
    return sum(artist_of(t) in theirs for t in radio) < AGREE_MIN


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)
    s = re.sub(r"\s+-\s+.*$", " ", s)                 # " - Remastered", " - Radio Edit"
    s = re.sub(r"\b(feat|ft|with)\b.*$", " ", s)
    s = re.sub(r"['’‘ʼ`]", "", s)
    return re.sub(r"[^\w]+", " ", s).strip()


def artist_of(t: dict) -> str:
    return norm((t.get("sub") or t.get("artist") or "").split(",")[0])


def title_of(t: dict) -> str:
    return norm(t.get("name") or t.get("title") or "")


def fuse(lists: list[list[dict]], weights: list[float] | None = None, k: float = RRF_K,
         drop=None) -> list[dict]:
    """Reciprocal rank fusion: a song scores w / (k + rank) in each list it is in, so songs
    several sources agree on lead. Matched by title|artist; the first copy is kept, with `_fused`
    and the smallest `_hop` of its copies. Songs `drop(t)` leaves out are not ranked, so what a
    list still has to give keeps its top ranks."""
    first, score, hop = {}, {}, {}
    for n, lst in enumerate(lists):
        w = weights[n] if weights else 1.0
        seen, rank = set(), 0
        for t in lst:
            key = f"{title_of(t)}|{artist_of(t)}"
            if not title_of(t) or key in seen or (drop and drop(t)):
                continue
            seen.add(key)
            first.setdefault(key, t)
            score[key] = score.get(key, 0.0) + w / (k + rank)
            rank += 1
            if "_hop" in t:
                hop[key] = min(hop.get(key, t["_hop"]), t["_hop"])
    return [dict(first[x], _fused=score[x], **({"_hop": hop[x]} if x in hop else {}))
            for x in sorted(score, key=lambda x: -score[x])]


def pick(cands: list[dict], n: int, seed_artist: str, heard_titles: set[str], heard_songs: set[str],
         banned: set[str], liked: set[str], favourite_artists: dict[str, float], wbw=lambda t: None,
         prefer_wbw: bool = True, rnd: random.Random | None = None,
         skipped_artists: dict[str, int] | None = None) -> list[dict]:
    """Up to `n` songs out of `cands` (best source first), varied and new: no
    other version of a heard title, banned keys left out, favourite artists
    nudged."""
    rnd = rnd or random.Random()
    seed = norm(seed_artist)
    skipped = skipped_artists or {}
    scored, seen_titles = [], set()
    for rank, t in enumerate(cands):
        title, who = title_of(t), artist_of(t)
        key = f"{title}|{who}"
        if not title or title in heard_titles or title in seen_titles or key in heard_songs or key in banned \
                or f"*|{who}" in banned or skipped.get(who, 0) >= SKIPS_OUT:
            continue
        seen_titles.add(title)
        fused = t.get("_fused")
        nudge = 1.0 if fused is None else 0.35      # fused: likes and habits tip, they do not lead
        score = -rank * 1.0 if fused is None else fused * FUSED
        score += nudge * 6.0 * favourite_artists.get(who, 0.0)
        if key in liked:
            score += nudge * 8.0
        k = wbw(t)
        if prefer_wbw and k in ("l", "n"):
            score -= nudge * 6.0
        score -= SKIP_STEP * skipped.get(who, 0)
        score += rnd.uniform(0, 4.0 * nudge * nudge)
        scored.append((score, t, who))
    scored.sort(key=lambda x: -x[0])

    out, per = [], {}
    pool = list(scored)
    last = seed
    since_seed = SEED_SHARE        # the seed's artist may come once early on
    while pool and len(out) < n:
        for i, (_s, t, who) in enumerate(pool):
            if per.get(who, 0) >= PER_ARTIST or who == last:
                continue
            if who == seed and since_seed < SEED_SHARE:
                continue
            break
        else:
            # Only the order rules can be eased; the cap per artist is kept, and the
            # next top-up (seeded by later songs) brings other artists.
            i = next((j for j, (_s, _t, w) in enumerate(pool) if per.get(w, 0) < PER_ARTIST), None)
            if i is None:
                break
        _s, t, who = pool.pop(i)
        out.append(t)
        per[who] = per.get(who, 0) + 1
        since_seed = 0 if who == seed else since_seed + 1
        last = who
    return out


def smooth(prev: dict | None, songs: list[dict], loud) -> list[dict]:
    """`songs` (in pick's order) reordered so none comes in much quieter than the song before it: each place
    takes, of the next SMOOTH_SPAN, the earliest-due once a drop past DROP_FREE costs DROP_STEP a dB, capped so
    a song waits at most SMOOTH_SPAN places. `loud(t)` is dB or None; unknown costs nothing."""
    out, rest = [], list(enumerate(songs))
    while rest:
        before = loud(prev) if prev is not None else None
        last = artist_of(prev) if prev is not None else ""
        best, at = None, 0
        for i, (due, t) in enumerate(rest[:SMOOTH_SPAN]):
            cost = float(due - len(out)) + (100.0 if last and artist_of(t) == last else 0.0)
            now = loud(t)
            if before is not None and now is not None:
                cost += min(float(SMOOTH_SPAN), DROP_STEP * max(0.0, before - now - DROP_FREE))
            if best is None or cost < best:
                best, at = cost, i
        prev = rest.pop(at)[1]
        out.append(prev)
    return out
