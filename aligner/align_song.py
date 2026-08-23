#!/usr/bin/env python3
"""Time the playing song against its own audio, on this machine.

    ./align_song.py --check          # what is installed, and what the card has
    ./align_song.py                  # fetch a copy, align it, delete it
    ./align_song.py --file song.wav  # align a file you already have

Spotify's stream is not a file this program can open, so a copy is fetched for
the few minutes the alignment takes and deleted straight after -- including if
the run fails partway. Only a copy the same length as the track is accepted: a
live take or a remix would align cleanly to the wrong performance, which is
worse than not aligning at all. Give it a local file and it skips all of that.

Nothing leaves the machine but the search and the download. The separation and
the alignment both run here, and both check the card has room before they touch
it -- see local_align.py. `--device cpu` never looks at the GPU at all.

The result is written as a .ttml named the way the S key names its files, so it
lands beside the rest and any of them can read it. Nothing in the player picks
it up on its own yet -- this is the test rig, not the feature.
"""
import argparse
import json
import pathlib
import re
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import local_align as LA       # noqa: E402
import lyric_sources as LS     # noqa: E402
import lyrics_gui as L         # noqa: E402
import spicy_lyrics as SL      # noqa: E402


def current():
    """(track id, metadata) for whatever the player has open."""
    io = L.MprisTransport()
    got = io.read(False)
    tid = None
    try:
        import dbus
        bus = dbus.SessionBus()
        obj = bus.get_object("org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2")
        meta = dbus.Interface(obj, "org.freedesktop.DBus.Properties").Get(
            L.MPRIS, "Metadata")
        tid = L.track_id(meta)
    except Exception:
        pass
    return io, tid, got


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
                        .filter(Boolean).join(", "),
            album: ((t.albumOfTrack || {}).name) || ""};
  } catch (e) { return null; }
})()"""


def named(tid):
    """Metadata for a track that is not the one playing."""
    from spotify_dom import connect
    got = connect(9222, "spotify").evaluate(JS_TRACK % json.dumps(
        "spotify:track:" + tid))
    if not got:
        raise SystemExit(f"no metadata for {tid}")
    return got


def document(tid, meta):
    """The words to align: Genius first, the player's chain only as a fallback.

    Genius is asked first for the same reason the player's aligner asks it --
    the chain ranks documents by how well they are TIMED, which picks the wrong
    song's line-synced lyrics over the right song's unsynced ones, and the
    timing is about to be measured from the audio anyway. See
    local_align.genius_doc().

    This is now the only document a run reads. The line times used to come from
    a second one, fetched from that same chain by title and artist, and on
    "LOSE MY NUMBER" it returned a stranger's song of the same name. They come
    from a speech model listening to the audio instead -- see
    local_align._model_points.
    """
    got = LA.genius_doc(L.load_token(), meta)
    if got:
        return got
    try:
        from spotify_dom import connect
        cdp = connect(9222, "spotify")
        body = (cdp.evaluate(SL.JS_GET % SL._j(
            SL.CACHE_NAME, SL.IDB_NAME, SL.IDB_STORE, tid)) or {}).get("body")
        if body:
            return body
    except Exception:
        pass
    info = {"title": meta["title"], "artist": meta["artist"],
            "album": meta["album"], "length": meta["length"]}
    for fn in (LS.from_amll, LS.from_netease, LS.from_lrclib):
        try:
            got = fn(tid, info)
        except Exception:
            continue
        if got:
            return got
    return None


def report(spare: float) -> None:
    """What is installed, and what the card has free at this moment.

    The VRAM line is the one worth reading twice. It is a reading, not a
    specification: the same machine says something different with a game open,
    and that is exactly the number both stages are about to be judged against.
    """
    for mod, why in (("torch", "the whole of it"),
                     ("torchaudio", "the aligner and its model"),
                     ("soundfile", "reading the audio"),
                     ("demucs", "separating the vocal")):
        try:
            got = __import__(mod)
            print(f"{mod:12s}: {getattr(got, '__version__', 'installed')}   ({why})")
        except ImportError:
            extra = ""
            if mod == "demucs" and shutil.which("demucs"):
                extra = "  (the command is on PATH; the library is what this wants)"
            print(f"{mod:12s}: MISSING for {sys.executable}{extra}\n"
                  f"             {sys.executable} -m pip install --user "
                  f"--break-system-packages {mod}")
    print(f"yt-dlp      : {'yes' if shutil.which('yt-dlp') else 'MISSING'}"
          f"   (fetching a copy to align)")
    print(f"ffmpeg      : {'yes' if shutil.which('ffmpeg') else 'MISSING'}"
          f"   (converting it)")

    # Stage three, all of it optional. Without any of it the words are timed
    # as words, which is what this did before syllables existed -- so these
    # are notes rather than warnings, and only ever about English.
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    for mod, why in (("phonemizer", "dividing English words by their sounds"),
                     ("transformers", "the phoneme model that times the division")):
        try:
            got = __import__(mod)
            print(f"{mod:12s}: {getattr(got, '__version__', 'installed')}   ({why})")
        except ImportError:
            print(f"{mod:12s}: not installed — English words stay whole   ({why})\n"
                  f"             {sys.executable} -m pip install --user "
                  f"--break-system-packages {mod}")
    print(f"espeak      : {espeak or 'MISSING — phonemizer has nothing to ask'}"
          f"   (the pronunciations themselves)")

    got = LA.survey()
    if got is None:
        print("GPU         : none usable — both stages would run on the CPU")
        return
    print(f"GPU         : {got['name']}, {got['free']:.1f} of {got['total']:.1f} GB free")
    for what, cost, window, unit in (
            ("separation", LA.DEMUCS_COST, LA.DEMUCS_WINDOW, "at a time"),
            # Not "at a time". The anchor stage holds the whole song, so what
            # the card affords it is a LENGTH OF SONG -- see local_align.ASR_COST.
            ("anchors   ", LA.ASR_COST, LA.ASR_WINDOW, "of song"),
            ("alignment ", LA.ALIGN_COST, LA.ALIGN_WINDOW, "at a time"),
            ("syllables ", LA.PHONE_COST, LA.PHONE_WINDOW, "at a time")):
        dev, win, why = LA.room("auto", cost, window, spare)
        print(f"  {what}: {dev}, {win:.1f}s {unit} — {why}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report what is installed and what the card has, then stop")
    ap.add_argument("--file", metavar="PATH", help="align this audio instead of fetching")
    ap.add_argument("--out", metavar="PATH", help="write to this path (extension ignored)")
    ap.add_argument("--track", metavar="ID",
                    help="align this Spotify track id instead of the playing one")
    ap.add_argument("--out-dir", metavar="DIR", default=".",
                    help="where the .ttml lands (default: here, beside the others)")
    ap.add_argument("--device", choices=["auto", "gpu", "cpu"], default=None,
                    help="auto uses the card only when there is room (default)")
    ap.add_argument("--stems", action=argparse.BooleanOptionalAction, default=None,
                    help="separate the vocal before aligning (default: yes)")
    ap.add_argument("--spare", type=float, default=None, metavar="GB",
                    help="VRAM to leave for everything else")
    ap.add_argument("--demucs-model", default=LA.MODEL, metavar="NAME")
    ap.add_argument("--no-anchors", action="store_true",
                    help="skip the speech model and align in one pass")
    ap.add_argument("--asr-model", metavar="NAME", default=None,
                    help=f"the speech model the anchors come from "
                         f"(default: {LA.ASR_MODEL}). Bigger hears more and "
                         f"wants more of the card: whisper-small, -medium, "
                         f"-large-v3, or any Whisper on Hugging Face")
    ap.add_argument("--acoustic", choices=["auto", "mms", "w2v"],
                    default="auto",
                    help="which model reads the audio. auto uses "
                         "wav2vec2-base-960h on English words and MMS_FA on "
                         "anything else, which is the only language "
                         "wav2vec2 knows; mms and w2v insist (default auto)")
    ap.add_argument("--syllable-lang", metavar="VOICE", default="",
                    help="divide words into syllables as this espeak voice "
                         "(es, de, fr, ja...) instead of detecting English. "
                         "The split is laid over the written word using "
                         "English spelling rules, so it is close for a "
                         "transparent orthography and rough for French — "
                         "check the result")
    ap.add_argument("--per-line", action="store_true",
                    help="time each line on its own instead of walking the "
                         "whole song, then settle overlapping pairs together "
                         "in a single pass")
    ap.add_argument("--asr-cpu", action="store_true",
                    help="let the speech model run on the processor when the "
                         "card has no room. It takes minutes and most of the "
                         "machine; without this the run simply goes unanchored")
    ap.add_argument("--debug", action="store_true",
                    help="say what each stage is doing, where it runs, and "
                         "what it is holding")
    ap.add_argument("--free", action="store_true",
                    help="drop the models when done rather than keeping them "
                         "loaded for the next song")
    ap.add_argument("--keep-vocals", metavar="PATH",
                    help="also write the separated vocal here, to listen to")
    ap.add_argument("--wait", type=float, default=0.0, metavar="SECS",
                    help="if the card is busy, wait up to this long for it "
                         "rather than falling back to the CPU")
    args = ap.parse_args()

    # The GUI holds these, as it held the Space and its token before it, so the
    # two agree about what this machine is willing to do to itself. A flag on
    # the command line still wins.
    saved = L.load_settings()
    device = args.device or saved.get("align_device", L.DEFAULTS["align_device"])
    stems = (saved.get("align_stems", L.DEFAULTS["align_stems"])
             if args.stems is None else args.stems)
    spare = float(args.spare if args.spare is not None
                  else saved.get("align_spare", L.DEFAULTS["align_spare"]))

    report(spare)
    if args.check:
        return 0

    if args.track:
        tid, m = args.track, named(args.track)
    else:
        _io, tid, meta = current()
        m = meta["meta"]
    print(f"\ntrack : {m['title']} — {m['artist']}  ({m['length']:.0f}s)")
    if not tid:
        print("no track id from the player")
        return 1
    doc = document(tid, m)
    if not doc:
        print("no lyrics to align")
        return 1
    words, _where = LA.words_of(doc)
    print(f"lyrics: {LS.quality(SL.payload(doc))}-timed, "
          f"{len(LS._items(SL.payload(doc)))} lines, {len(words)} words")

    if not words:
        # Said here rather than blamed on the aligner. align() returns None for
        # several unrelated reasons and the first version reported all of them
        # as "no answer", which pointed at the network for a document that had
        # simply been read wrongly.
        print("no words in that document to align")
        return 1

    if args.wait > 0 and device != "cpu" and LA.survey() is not None:
        if not wait_for_card(args.wait, spare, stems):
            print("  still busy after the wait — going ahead with what there is")

    def run(audio):
        print("\naligning…")
        t0 = time.monotonic()
        got = LA.align(audio, doc, stems=stems, want=device, spare=spare,
                       name=args.demucs_model, keep=args.keep_vocals,
                       anchors=not args.no_anchors, asr=args.asr_model,
                       asr_cpu=args.asr_cpu, debug=args.debug,
                       target=float(m.get("length") or 0.0),
                       syl_lang=args.syllable_lang,
                       acoustic=args.acoustic, per_line=args.per_line,
                       log=print)
        took = time.monotonic() - t0
        if got is None:
            print(f"nothing usable after {took:.0f}s"
                  + (f"\n  {LA.align.last_error}" if LA.align.last_error else ""))
            for line in LA.align.last_trace:
                print(f"    {line}")
        else:
            print(f"done in {took:.0f}s")
        return got

    if args.file:
        out = run(args.file)
    else:
        query = f"{m['artist']} {m['title']}"
        print(f"\nlooking for a copy the same length as the track "
              f"({m['length']:.0f}s +/- {LA.LENGTH_TOL:.0f}s)…")
        # The copy exists only inside this block. Whatever happens in it --
        # a refusal, a timeout, Ctrl+C -- the file is gone on the way out.
        with LA.fetched(query, m["length"] or 0.0,
                        artist=m.get("artist", ""), tid=tid) as audio:
            if not audio:
                print(f"no copy to align: {LA.fetched.last_error}")
                print("  A live take or a remix would align to the wrong "
                      "performance, so a copy of the wrong length is refused "
                      "rather than guessed at.")
                return 1
            size = pathlib.Path(audio).stat().st_size // 1024
            print(f"fetched {size} KB, aligning, then deleting it")
            out = run(audio)
        print("temporary copy deleted")
    if args.free:
        # The weights outlive the stage that wanted them, which is right for
        # the player and wasteful for one run of this. Dropped here rather than
        # inside align(), because whether a second song is coming is the
        # caller's question and not the aligner's.
        LA.release()
        if args.debug:
            print(f"models dropped — ram now {LA._rss():.1f}G, "
                  f"vram {LA._held():.1f}G")
    if out is None:
        return 1

    items = LS._items(SL.payload(out))
    timed = sum(1 for it in items
                if isinstance(it.get("Lead"), dict) and it["Lead"].get("Syllables"))
    print(f"{timed} of {len(items)} lines word-timed "
          f"({timed / max(1, len(items)) * 100:.0f}%)")
    # The rest are not necessarily dark. A line the aligner could not place but
    # the speech model heard is line-timed, which lights on cue without its
    # words lighting one by one -- worth distinguishing from a line with no
    # timing at all, and the two used to be reported as one number.
    spoke = int(SL.payload(out).get("_heard_only") or 0)
    shared = int(SL.payload(out).get("_shared") or 0)
    dark = len(items) - timed - spoke - shared
    if spoke or shared or dark:
        print(f"  {spoke} line-timed from the speech model, "
              f"{shared} shared across a measured gap, {dark} untimed")

    # Written as TTML, named the way the S key names its files, so an aligned
    # song lands beside the rest and can be opened, diffed or re-read by
    # anything that already understands them. The JSON goes alongside it only
    # because it is what the player's own loader reads back.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_",
                  f"{m['artist']} - {m['title']}".strip(" -"))[:120] or tid
    stem = (pathlib.Path(args.out).with_suffix("") if args.out
            else pathlib.Path(args.out_dir).expanduser() / name)
    ttml = stem.with_suffix(".ttml")
    raw_json = stem.with_suffix(".aligned.json")
    try:
        ttml.parent.mkdir(parents=True, exist_ok=True)
        ttml.write_text(SL.render(out, "ttml") + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"could not write TTML: {exc}")
        return 1
    raw_json.write_text(json.dumps(out), encoding="utf-8")
    kb = ttml.stat().st_size / 1024
    print(f"written  {ttml}  ({kb:.0f} KB)")
    print(f"         {raw_json.name}")
    return 0


def wait_for_card(limit: float, spare: float, stems: bool) -> bool:
    """Sit until the card has room for the heavier stage, or until `limit`.

    Worth having because the alternative is not "fail" but "quietly take ten
    times as long on the CPU", and the usual reason a card is full is something
    that will finish -- another model, an export, a game being closed. Nothing
    is downloaded or loaded until this returns, so waiting costs nothing.

    Only called when there is a card at all, so returning False here means the
    wait ran out rather than that there was never anything to wait for.
    """
    cost, window = ((LA.DEMUCS_COST, LA.DEMUCS_WINDOW) if stems
                    else (LA.ALIGN_COST, LA.ALIGN_WINDOW))
    end = time.monotonic() + limit
    said = False
    while True:
        dev, _win, why = LA.room("auto", cost, window, spare)
        if dev != "cpu":
            if said:
                print(f"  the card came free — {why}")
            return True
        if LA.survey() is None or time.monotonic() >= end:
            return False
        if not said:
            print(f"\nwaiting up to {limit:.0f}s for the card — {why}")
            said = True
        time.sleep(min(10.0, max(1.0, end - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
