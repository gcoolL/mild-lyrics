#!/usr/bin/env python3
"""Cut the cached word-synced songs into training clips.

    ./build_dataset.py --songs 200 --out ~/.cache/mild-lyrics/dataset

The acoustic model this aligner reads with was trained on people reading
sentences out loud. It is asked about singing, which is slower, held, pitched,
and mixed under a band -- and it does the job well enough to be useful and
badly enough to be worth improving. Improving it needs examples of singing with
the words written down, which is exactly what the player's cache has been
quietly accumulating: every song played that had word-synced lyrics.

One clip per LINE, cut on the reference's own timings. Lines rather than whole
songs because a transformer's cost grows with the square of its input and a
four-minute song will not fit on this card; and lines rather than words because
a word on its own has no context to be recognised in.

Resumable on purpose. It fetches a copy of every song, which takes about a
minute each, and a run over two hundred of them is long enough that it will be
interrupted.
"""
import argparse
import json
import pathlib
import sys
import statistics
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import local_align as LA       # noqa: E402
import lyric_sources as LS     # noqa: E402
import spicy_lyrics as SL      # noqa: E402

JS_TRACK = """(async () => {
  try {
    const r = await Spicetify.GraphQL.Request(
      Spicetify.GraphQL.Definitions.getTrack, {uri: %s});
    const t = ((r.data || {}).trackUnion) || {};
    if (!t.name) return null;
    const arts = [...(((t.firstArtist || {}).items) || []),
                  ...(((t.otherArtists || {}).items) || [])];
    return {title: t.name,
            length: (((t.duration || {}).totalMilliseconds) || 0) / 1000,
            artist: arts.map(x => ((x.profile) || {}).name)
                        .filter(Boolean).join(", ")};
  } catch (e) { return null; }
})()"""

MIN_CLIP = 0.6
MAX_CLIP = 12.0
CLIP_PAD = 0.15


def lines_of(doc) -> list[tuple[float, float, str]]:
    """(start, end, text) per line, from a word-synced document."""
    out = []
    for item in LS._items(SL.payload(doc)):
        lead = item.get("Lead")
        if not isinstance(lead, dict):
            continue
        syls = lead.get("Syllables") or []
        if not syls:
            continue
        words, word = [], ""
        for syl in syls:
            word += str(syl.get("Text") or "")
            if not syl.get("IsPartOfWord"):
                if word.strip():
                    words.append(word.strip())
                word = ""
        if word.strip():
            words.append(word.strip())
        lo = syls[0].get("StartTime")
        hi = syls[-1].get("EndTime")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and words:
            out.append((float(lo), float(hi), " ".join(words)))
    return out


OFFSETS = LS.cache_root() / "offsets.json"
COMMUNITY = "spl"
LAG_MIN = 0.05


def measured_offsets() -> dict:
    """Per-song displacement against the reference, by name, or {}.

    THE CLIPS ARE CUT ON SOMEBODY ELSE'S TIMINGS, against audio fetched from
    somewhere else, and about a quarter of copies are displaced against the
    master their reference was made from -- by 0.13s to over a second, with
    the alignment inside them otherwise near perfect. On a three second line
    that is a large fraction of the clip holding audio belonging to different
    words, taught to the model as if it were right. Both fine-tuning runs that
    measured nothing were trained on data cut this way.

    These numbers are MEASURED -- our alignment against the song's reference,
    the same quantity the onset test confirmed on 39 tight-scatter songs of 42
    -- and only for songs whose error is tight enough that its median is a
    displacement rather than the middle of a mess.

    What this replaced, and why: the first version estimated the shift per song
    by asking which one landed the reference's line starts on the copy's own
    energy peaks. Checked against 104 songs that had both, it agreed within
    0.1s on 61% and was SIGN-FLIPPED on a good few -- +0.13s where the truth
    was -0.28s, +0.30s where it was -0.35s -- which moves those clips further
    from their words rather than nearer. Confidence did not separate the good
    from the bad: one sign flip came in at 6.2σ. Maximising energy coincidence
    can lock onto the beat instead of the voice, and a drum hit half a beat
    away scores every bit as sharply as the vocal.

    So: right where it speaks, silent otherwise. A song with no measurement is
    cut exactly as it always was.
    """
    try:
        return json.loads(OFFSETS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def usable(text: str) -> str:
    """The line as the model spells it, or '' if it cannot be taught from.

    The model's alphabet is a-z and the apostrophe. A line that survives
    flattening as mostly nothing -- another script, an instrumental marker --
    would teach it to hear words that are not being sung.
    """
    flat = " ".join(w for w in (LA._flat(x) for x in text.split()) if w)
    if not flat or len(flat) < 4:
        return ""
    return flat


def words_of(body) -> list[str]:
    """Every word in a cached document, for comparing against a transcript."""
    return [w for _lo, _hi, text in lines_of(body) for w in text.split()]


def right_song(wave, rate, mine: list[str], decoys: list[list[str]],
               spare: float) -> tuple[bool, str]:
    """Is this audio the song these lyrics belong to?

    The fetch path can return a different recording entirely -- one held-out
    song turned out to be somebody else's track of the same length, and nothing
    ever noticed. A clip cut from the wrong recording pairs real singing with
    unrelated words, which is not a hard example, it is a wrong label.

    Against a null, not a threshold: "how much of the lyric did the speech model
    hear" mostly measures how well it hears the genre, so the same question is
    asked of songs this definitely is NOT. A right recording sits far above its
    own floor; a wrong one sits on it.
    """
    dev, chunk, _why = LA.room("gpu", LA.ASR_COST, LA.ASR_WINDOW, spare)
    if dev != "cpu":
        LA._cap(spare)
    LA.heard.why = ""
    said = LA.heard(wave, rate, dev, None, None, chunk=chunk)
    if not said:
        return True, f"could not listen ({LA.heard.why})"
    theirs = {LA._flat(w["word"]) for w in said if w.get("word")}
    theirs.discard("")

    def share(text):
        want = {LA._flat(w) for w in text}
        want.discard("")
        return len(theirs & want) / max(1, len(want))

    a = share(mine)
    n = statistics.median([share(d) for d in decoys]) if decoys else 0.0
    if n < LA.NULL_FLOOR:
        return True, f"nothing to compare against (songs it is not scored {n*100:.0f}%)"
    return (a - n >= LA.HEARD_MARGIN,
            f"heard {a*100:.0f}% of its words against {n*100:.0f}% for songs "
            f"it is not")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(LS.cache_root() / "dataset"))
    ap.add_argument("--songs", type=int, default=200)
    ap.add_argument("--spare", type=float, default=0.4)
    args = ap.parse_args()

    import numpy as np
    out = pathlib.Path(args.out).expanduser()
    (out / "clips").mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.jsonl"
    done = set()
    if manifest.exists():
        for row in manifest.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(row)["tid"])
            except Exception:
                continue
    print(f"{len(done)} songs already in the dataset")

    from spotify_dom import connect
    cdp = connect(9222, "spotify")
    ids = cdp.evaluate(SL.JS_IDS % json.dumps(SL.CACHE_PREFIX)) or []

    import random
    decoys = []
    for tid in random.Random(0).sample(ids, min(40, len(ids))):
        got = cdp.evaluate(SL.JS_GET % SL._j(
            SL.CACHE_PREFIX, SL.IDB_NAME, SL.IDB_STORE, tid)) or {}
        body = got.get("body")
        if body and LS.quality(SL.payload(body)) == "syllable":
            words = words_of(body)
            if len(words) > 40:
                decoys.append(words)
        if len(decoys) >= 4:
            break
    print(f"comparing against {len(decoys)} unrelated songs")

    offsets = measured_offsets()
    if offsets:
        print(f"  {len(offsets)} song(s) have a measured offset to cut at")
    added = clips = wrong = shifted = foreign = 0
    secs = 0.0
    with manifest.open("a", encoding="utf-8") as log:
        for tid in ids:
            if added >= args.songs:
                break
            if tid in done:
                continue
            got = cdp.evaluate(SL.JS_GET % SL._j(
                SL.CACHE_PREFIX, SL.IDB_NAME, SL.IDB_STORE, tid)) or {}
            body = got.get("body")
            if not body:
                continue
            doc = SL.payload(body)
            if LS.quality(doc) != "syllable":
                continue
            if str(doc.get("source") or "") != COMMUNITY:
                foreign += 1
                continue
            rows = lines_of(body)
            if len(rows) < 6:
                continue
            meta = cdp.evaluate(JS_TRACK % json.dumps("spotify:track:" + tid))
            if not meta or not meta.get("length"):
                continue
            name = f"{meta['artist'][:22]} - {meta['title'][:26]}"
            t0 = time.monotonic()
            try:
                with LA.fetched(f"{meta['artist']} {meta['title']}",
                                float(meta["length"]),
                                artist=meta.get("artist", ""), tid=tid) as audio:
                    if not audio:
                        print(f"  skip {name}: {LA.fetched.last_error[:40]}")
                        continue
                    wave, rate = LA._read(audio)
                    keep, why = right_song(wave, rate, words_of(body), decoys,
                                           args.spare)
                    if not keep:
                        print(f"  SKIP {name}: not this recording — {why}")
                        wrong += 1
                        continue
                    dev, win, _why = LA.room("gpu", LA.DEMUCS_COST,
                                             LA.DEMUCS_WINDOW, args.spare)
                    stem, srate = LA.separate(wave, rate, dev, win, LA.MODEL,
                                              None, None)
                    mono = LA._resample(LA._channels(stem, 1), srate, LA.RATE)[0]
            except Exception as exc:
                print(f"  skip {name}: {type(exc).__name__}")
                continue
            finally:
                LA.release()

            lag = float(offsets.get(f"{meta['artist']} - {meta['title']}", 0.0))
            if abs(lag) < LAG_MIN:
                lag = 0.0
            else:
                shifted += 1
                print(f"  {name:52} copy runs {lag:+.2f}s against the "
                      f"reference — cutting there instead")

            kept = []
            for k, (lo, hi, text) in enumerate(rows):
                flat = usable(text)
                if not flat:
                    continue
                lo, hi = lo + lag, hi + lag
                a = max(0.0, lo - CLIP_PAD)
                b = min(len(mono) / LA.RATE, hi + CLIP_PAD)
                if not (MIN_CLIP <= b - a <= MAX_CLIP):
                    continue
                piece = mono[int(a * LA.RATE):int(b * LA.RATE)]
                if piece.numel() < int(MIN_CLIP * LA.RATE):
                    continue
                path = out / "clips" / f"{tid}_{k:04d}.npy"
                np.save(path, piece.numpy().astype("float32"))
                kept.append({"clip": path.name, "text": flat,
                             "secs": round(float(b - a), 3)})
            if not kept:
                print(f"  skip {name}: no usable lines")
                continue
            log.write(json.dumps({"tid": tid, "name": name,
                                  "lines": kept}) + "\n")
            log.flush()
            added += 1
            clips += len(kept)
            secs += sum(x["secs"] for x in kept)
            print(f"  {name:52} {len(kept):3} clips  "
                  f"{sum(x['secs'] for x in kept):6.1f}s  "
                  f"({time.monotonic() - t0:.0f}s)")

    print(f"\nadded {added} songs, {clips} clips, {secs / 3600:.2f} hours"
          + (f"; skipped {wrong} song(s) whose audio was not the song"
             if wrong else "")
          + (f"; cut {shifted} song(s) at a corrected offset"
             if shifted else "")
          + (f"; passed over {foreign} song(s) not community-uploaded"
             if foreign else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
