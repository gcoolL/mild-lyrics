#!/usr/bin/env python3
"""Make a synced lyric file for a song, from the command line.

    ./ttml.py                             the song Spotify is playing now
    ./ttml.py "ToxiPlays wordle freestyle"
    ./ttml.py --url https://youtu.be/...  when the search finds the wrong copy
    ./ttml.py "song" --format elrc        ttml (default), elrc, lrc, json, text
    ./ttml.py "song" --audio              keep the audio next to the file

Everything the aligner knows how to do, in one command: find the song, get its
lyrics from Genius, fetch a copy, separate the vocal, align the words, cut them
into syllables, and write the result.

It also says what it thinks of its own answer:

  heard    how much of the lyric the speech model found in the audio, against
           how much it finds in songs this is NOT. A copy that scores no better
           than unrelated songs is not this recording -- which happens, and
           used to happen silently.

What it no longer says is `packed` -- the share of neighbouring words landing
under 0.1s apart, printed here for a while as a stretch-and-squeeze warning.
Measured against 278 songs with word-synced references it does not work: its
correlation with the share of words placed correctly is -0.16, and with the
share badly lost, -0.05, which is the wrong sign. The 12% cutoff flagged the
best song in the cache (87% of words inside 0.1s) and passed the worst (0%).
It is still on the document as `_packed` for anything that wants to look, but
it is not shown, because a warning that anti-correlates with the fault it
claims to detect is worse than no warning.
"""
import argparse
import json
import pathlib
import shutil
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
# Data lives beside the code's folder, not inside it.
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import local_align as LA        # noqa: E402
import lyric_sources as LS      # noqa: E402
import lyrics_gui as L          # noqa: E402
import spicy_lyrics as SL       # noqa: E402

JS_PLAYING = """(() => {
  const P = Spicetify && Spicetify.Player;
  if (!P) return null;
  const d = P.data || {};
  const it = d.item || d.track || {};
  return {uri: it.uri || "", title: it.name || "",
          artist: (it.artists || []).map(a => a && a.name).filter(Boolean).join(", "),
          length: ((it.duration || {}).milliseconds
                   || (it.duration || {}).totalMilliseconds || 0) / 1000};
})()"""

JS_TRACK = """(async () => {
  try {
    const r = await Spicetify.GraphQL.Request(
      Spicetify.GraphQL.Definitions.getTrack, {uri: %s});
    const t = ((r.data || {}).trackUnion) || {};
    if (!t.name) return null;
    const a = [...(((t.firstArtist || {}).items) || []),
               ...(((t.otherArtists || {}).items) || [])];
    return {title: t.name,
            length: (((t.duration || {}).totalMilliseconds) || 0) / 1000,
            artist: a.map(x => ((x.profile) || {}).name).filter(Boolean).join(", ")};
  } catch (e) { return null; }
})()"""

INDEX = pathlib.Path.home() / ".cache/mild-lyrics/tracks.json"


def index(cdp, refresh: bool = False) -> dict:
    """Every song in the lyrics cache, by track id, kept on disk.

    Spotify's search API is not reachable from here -- CosmosAsync returns an
    error object and the GraphQL search definition does not match this
    Spicetify -- and asking it about 600 tracks one at a time takes minutes.
    So it is asked once and the answers are kept: the cache only grows when
    something new is played, and --refresh picks those up.
    """
    got = {}
    if INDEX.exists() and not refresh:
        try:
            got = json.loads(INDEX.read_text(encoding="utf-8"))
        except Exception:
            got = {}
    ids = cdp.evaluate("""(async () => {
          const c = await caches.open(%s);
          return (await c.keys()).map(r => r.url.split('/').pop());
        })()""" % json.dumps(SL.CACHE_NAME)) or []
    fresh = [t for t in ids if t not in got]
    if fresh:
        print(f"  learning {len(fresh)} song(s) new to the cache…", flush=True)
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        for n, tid in enumerate(fresh, 1):
            meta = cdp.evaluate(JS_TRACK % json.dumps("spotify:track:" + tid))
            if meta and meta.get("title"):
                got[tid] = meta
            # Written as it goes, not at the end: the first run asks Spotify
            # about six hundred songs one at a time, and losing all of it to an
            # interrupted run means starting from nothing every time.
            if n % 25 == 0 or n == len(fresh):
                INDEX.write_text(json.dumps(got), encoding="utf-8")
                print(f"    {n} of {len(fresh)}", flush=True)
    return got


def _terms(text: str) -> list[str]:
    """A query or a title as words worth matching on.

    Flattened one word at a time, not all at once: _flat() drops everything
    that is not a letter, spaces included, so flattening the whole string glues
    it into a single token and makes word ORDER matter -- "birthday
    wifiskeleton" then never matches "wifiskeleton - birthday". Digits survive
    on their own, because a song may be called 505.
    """
    out = []
    for word in text.lower().replace("-", " ").split():
        flat = LA._flat(word)
        keep = flat or "".join(c for c in word if c.isalnum())
        if keep:
            out.append(keep)
    return out


def look_up(cdp, query: str, refresh: bool = False):
    """The cached song best matching `query`, or None."""
    want = _terms(query)
    if not want:
        return None
    best, score = None, 0
    for tid, meta in index(cdp, refresh).items():
        hay = set(_terms(f"{meta['artist']} {meta['title']}"))
        hit = sum(1 for w in want if w in hay)
        if hit > score:
            best, score = dict(meta, uri="spotify:track:" + tid), hit
    # Every word but one has to land, so "wordle freestyle" is not answered
    # with some other freestyle.
    return best if score >= max(1, len(want) - 1) else None


def spotify():
    from spotify_dom import connect
    got = connect(9222, "spotify")
    if got is None:
        sys.exit("Spotify is not reachable on port 9222 — start it with "
                 "Spicetify and try again.")
    return got


def decoys(cdp, n=6):
    """A few songs this is definitely not, to compare the transcript against.

    Without them "did the model hear this song's words" mostly measures how
    well it hears the genre: a correct lo-fi track scored 42% where a wrong
    recording scored 34%. Against a floor of unrelated songs the same two are
    +24% and +4%, which is a difference worth acting on.
    """
    try:
        ids = cdp.evaluate("""(async () => {
              const c = await caches.open(%s);
              return (await c.keys()).map(r => r.url.split('/').pop());
            })()""" % json.dumps(SL.CACHE_NAME)) or []
    except Exception:
        return []
    # Sampled, not the first few: the cache is in the order songs were played,
    # so taking the front of it can hand back six songs by the same artist --
    # a floor made of the very vocabulary being tested for.
    import random
    ids = list(ids)
    random.Random(0).shuffle(ids)
    out = []
    for tid in ids:
        if len(out) >= n:
            break
        try:
            got = cdp.evaluate(SL.JS_GET % SL._j(
                SL.CACHE_NAME, SL.IDB_NAME, SL.IDB_STORE, tid)) or {}
            body = got.get("body")
            if not body:
                continue
            words = [w for item in LS._items(SL.payload(body))
                     for syl in ((item.get("Lead") or {}).get("Syllables") or [])
                     for w in str(syl.get("Text") or "").split()]
            if len(words) > 40:
                out.append(words)
        except Exception:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Make a synced lyric file for a song.")
    ap.add_argument("song", nargs="?", default="",
                    help="artist and title; omit for whatever is playing")
    ap.add_argument("--url", default="",
                    help="the copy to use, when the search picks the wrong one")
    ap.add_argument("--format", default="ttml",
                    choices=["ttml", "elrc", "lrc", "json", "text"])
    ap.add_argument("--out", default=str(ROOT / "lyrics"),
                    help="where to write it")
    ap.add_argument("--audio", action="store_true",
                    help="keep the audio beside the file, to listen along")
    ap.add_argument("--no-onsets", action="store_true",
                    help="skip the spectrogram pass (it is on by default)")
    ap.add_argument("--spare", type=float, default=0.4,
                    help="GB of VRAM to leave for everything else")
    ap.add_argument("--refresh", action="store_true",
                    help="re-read every song from Spotify, not just new ones")
    ap.add_argument("--quiet", action="store_true", help="only the result")
    args = ap.parse_args()

    cdp = spotify()
    if args.song:
        meta = look_up(cdp, args.song, args.refresh)
        if not meta:
            return say_no(f"No song in the lyrics cache matches "
                          f"{args.song!r}. Play it once in Spotify so its "
                          f"lyrics are cached, then try again.")
    else:
        meta = cdp.evaluate(JS_PLAYING)
        if not meta or not meta.get("title"):
            return say_no("Nothing is playing, and no song was named.")
    tid = (meta.get("uri") or "").rsplit(":", 1)[-1]
    name = f"{meta['artist']} - {meta['title']}"
    log = None if args.quiet else (lambda m: print(f"  {str(m).strip()}"))
    print(f"{name}  ({meta.get('length', 0):.0f}s)")

    doc = LA.genius_doc(L.load_token(), meta)
    if not doc:
        return say_no("Genius has no lyrics for it.")

    # A copy named on the command line is believed and remembered: the search
    # matches on title and length, and a different recording of the right
    # length is exactly the failure it cannot see.
    if args.url and tid:
        LS.pin_source(tid, args.url)
        print(f"  using {args.url}")

    t0 = time.monotonic()
    try:
        with LA.fetched(f"{meta['artist']} {meta['title']}",
                        float(meta.get("length") or 0), artist=meta["artist"],
                        tid=tid) as audio:
            if not audio:
                return say_no(f"No copy could be fetched — "
                              f"{LA.fetched.last_error}")
            got = LA.align(audio, doc, want="gpu", spare=args.spare,
                           target=float(meta.get("length") or 0) or None,
                           decoys=decoys(cdp), onsets=not args.no_onsets,
                           log=log)
            if got is not None and args.audio:
                out = pathlib.Path(args.out).expanduser()
                out.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(audio, out / (safe(name) + pathlib.Path(audio).suffix))
    finally:
        LA.release()

    if got is None:
        return say_no(f"Could not align it — {LA.align.last_error}")

    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    ext = {"ttml": "ttml", "elrc": "lrc", "lrc": "lrc",
           "json": "json", "text": "txt"}[args.format]
    where = out / f"{safe(name)}.{ext}"
    where.write_text(SL.render(got, args.format) + "\n", encoding="utf-8")

    share, null = got.get("_heard_share"), got.get("_heard_null")
    print(f"\n  {where}")
    print(f"  {time.monotonic() - t0:.0f}s")
    if share is None:
        print("  the recording could not be checked against the words")
    else:
        margin = share - (null or 0.0)
        print(f"  heard {share*100:.0f}% of the words, against "
              f"{(null or 0)*100:.0f}% for songs this is not"
              + ("   <-- THIS IS PROBABLY NOT THE RIGHT RECORDING; pass "
                 "--url with the right one" if margin < 0 else
                 "   (a thin margin — worth a listen, but heavily produced "
                 "songs score low even when the copy is right)"
                 if margin < LA.HEARD_MARGIN else ""))
    return 0


def safe(name: str) -> str:
    return "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "song"


def say_no(why: str) -> int:
    print(f"  {why}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
