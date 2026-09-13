"""One command for the whole synchroniser.

    python -m sync.sync snapshot          keep every spl lyric on disk
    python -m sync.sync train             a model from noise
    python -m sync.sync bench             measure it on songs it never saw
    python -m sync.sync offsets           measure where each copy sits
    python -m sync.sync dataset           cut clips (at those offsets)
    python -m sync.sync train --more 5000 carry on training
    python -m sync.sync ttml "song"       write a synced lyric file
    python -m sync.sync status            what exists so far

The order above is the loop, and it is a loop on purpose: the model measures
the copies, the measurements fix the clips, the clips train the model. Nothing
in it borrows an alignment from anywhere else, which is the whole point -- the
first pass is trained on clips cut where a stranger's timings said, and every
pass after that on clips cut where this model heard the singing.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "aligner"))

from sync import (bench, data, dataset, encoder, generate, library,  # noqa: E402
                  offset, train)

HOME = pathlib.Path.home() / ".cache/mild-lyrics/sync"


def _default_ckpt() -> pathlib.Path:
    """The model to use when none is named.

    A checkpoint with a trained boundary head wins, because the word ENDS come
    from it and a model without one can only guess them from the letters. Among
    those, the newest. `syncnet.pt` is the bare fallback, and it is a fallback
    rather than the default because that name has held a throwaway before now.

    `mmap=True` for the same reason `ckpt_facts` gives: the question is two
    scalars and a list of key names, and these files are a gigabyte each. A
    plain load unpickles every weight to answer it -- 1.38s a checkpoint here
    against 0.20s, and a gigabyte of resident memory per file that is dropped
    on the next line. The fallback is for a checkpoint saved before torch's
    zipfile format, which cannot be mapped.
    """
    import torch
    best = None
    for path in sorted(HOME.glob("syncnet*.pt")):
        try:
            try:
                got = torch.load(path, map_location="cpu", weights_only=False,
                                 mmap=True)
            except Exception:               # not a zipfile save, or old torch
                got = torch.load(path, map_location="cpu", weights_only=False)
        except Exception:
            continue
        has = any(k.startswith("boundary.") for k in got.get("weights", {}))
        rank = (has, int(got.get("step") or 0))
        if best is None or rank > best[0]:
            best = (rank, path)
    return best[1] if best else HOME / "syncnet.pt"


def _shipped(args, which: str) -> float:
    """What the generator would use for this, unless the flag says otherwise.

    The benchmark and the generator have to agree about their defaults or the
    benchmark is measuring an aligner nobody runs. Reading the constant rather
    than restating it is what makes that true tomorrow as well as today.
    """
    got = getattr(args, which, None)
    return float(getattr(generate, which.upper()) if got is None else got)


def _safe(name: str) -> str:
    return "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "song"


def _playing(cdp):
    return cdp.evaluate("""(() => {
      const P = Spicetify && Spicetify.Player;
      if (!P) return null;
      const d = P.data || {}; const it = d.item || d.track || {};
      return {uri: it.uri || "", title: it.name || "",
              artist: (it.artists || []).map(a => a && a.name).filter(Boolean).join(", "),
              length: ((it.duration || {}).milliseconds
                       || (it.duration || {}).totalMilliseconds || 0) / 1000};
    })()""")


def _find(query: str) -> tuple[str, dict] | tuple[None, None]:
    """The snapshotted song best matching a query, by title and artist words."""
    from sync import text as T
    tracks = dataset._tracks()
    want = [T.flatten(w) or w for w in query.lower().replace("-", " ").split()]
    best, hits = None, 0
    for tid, meta in tracks.items():
        hay = {T.flatten(w) or w for w in
               f"{meta.get('artist', '')} {meta.get('title', '')}".lower().split()}
        got = sum(1 for w in want if w in hay)
        if got > hits:
            best, hits = (tid, meta), got
    # Every word but one has to land, so "wordle freestyle" does not come back
    # with some other freestyle.
    return best if best and hits >= max(1, len(want) - 1) else (None, None)


def cmd_ttml(args) -> int:
    import spicy_lyrics as SL
    if args.song:
        tid, meta = _find(args.song)
        if not tid:
            raise SystemExit(f"no song in {pathlib.Path.home()}/.cache/"
                             f"mild-lyrics/tracks.json matches {args.song!r} "
                             f"-- play it once, then run `sync snapshot`")
    else:
        from spotify_dom import connect
        cdp = connect(9222, "spotify")
        if cdp is None:
            raise SystemExit("nothing named, and Spotify is not reachable")
        meta = _playing(cdp)
        if not meta or not meta.get("title"):
            raise SystemExit("nothing is playing, and no song was named")
        tid = (meta.get("uri") or "").rsplit(":", 1)[-1]
    name = f"{meta['artist']} - {meta['title']}"
    print(f"{name}  ({meta.get('length', 0):.0f}s)")

    doc = generate.make(meta, tid, args.ckpt, device=args.device,
                        stem=args.stem, spare=args.spare,
                        any_source=args.any_source, gate=args.gate,
                        attack=args.attack, fallback=args.fallback,
                        lean=args.lean, uncrush=args.uncrush,
                        repace=args.repace,
                        onattack=args.onattack,
                        sustain=args.ttml_sustain,
                        log=lambda m: print(f"  {m}"))
    out = pathlib.Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    ext = {"ttml": "ttml", "elrc": "lrc", "lrc": "lrc", "json": "json",
           "text": "txt"}[args.format]
    where = out / f"{_safe(name)}.{ext}"
    where.write_text(SL.render(doc, args.format) + "\n", encoding="utf-8")
    print(f"  {where}")
    return 0


def cmd_status(args) -> int:
    from sync import model as M
    print(f"snapshot  {len(list(dataset.SNAP.glob('*.json')))} spl lyric(s) "
          f"in {dataset.SNAP}")
    for root in (data.DATA, dataset.DATA):
        try:
            got = data.songs(root)
            clips = sum(len(s["lines"]) for s in got)
            held = sum(1 for s in got if data.held(s["name"]))
            print(f"dataset   {len(got):4} songs, {clips:5} clips in {root} "
                  f"({held} held back)")
        except SystemExit:
            print(f"dataset   nothing at {root}")
    lags = offset.load()
    good = sum(1 for v in lags.values() if v.get("trusted"))
    print(f"offsets   {len(lags)} measured, {good} tight enough to cut at")
    if pathlib.Path(args.ckpt).exists():
        net, rest = M.load(args.ckpt)
        hist = rest.get("history") or []
        last = hist[-1] if hist else {}
        print(f"model     {net.size()}, step {rest.get('step')}, "
              f"held loss {last.get('held', '?')}, heard "
              f"{(last.get('heard') or 0)*100:.1f}%, calibration "
              f"{rest.get('calibration', 0):+.3f}s")
    else:
        print(f"model     nothing at {args.ckpt}")
    latest = sorted(bench.REPORTS.glob("bench-*.md")) if bench.REPORTS.exists() else []
    if latest:
        print(f"bench     {len(latest)} report(s), newest {latest[-1].name}")
        try:
            got = json.loads((HOME / "bench.json").read_text())["summary"]
            print(f"          {got['songs']} songs, typical error "
                  f"{got['size']:.3f}s, within 0.3s {got['near']*100:.0f}%")
        except Exception:
            pass
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="sync", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # Resolved after parsing, not here: working out the default reads every
    # checkpoint on the machine, and naming one on the command line -- or
    # asking for --help -- should not pay for the walk.
    ap.add_argument("--ckpt", default=None, help="which model to use")
    ap.add_argument("--device", default="cuda")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("snapshot", help="keep every spl lyric on disk")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--apple", action="store_true",
                   help="keep Apple Music's word-synced lyrics instead, for "
                        "training only -- the benchmark never reads them")
    p.set_defaults(run=lambda a: dataset.snapshot(a.limit, a.apple))

    p = sub.add_parser("dataset", help="cut clips to train on")
    p.add_argument("--songs", type=int, default=50)
    p.add_argument("--out", default=str(dataset.DATA))
    p.add_argument("--pad", type=float, default=dataset.PAD)
    p.add_argument("--spare", type=float, default=0.4)
    p.add_argument("--stem", action="store_true",
                   help="separate the vocal first (off by default)")
    p.add_argument("--recut", action="store_true",
                   help="cut songs already in the dataset again, at an offset "
                        "measured in the same pass against the same copy")
    p.add_argument("--group", type=int, default=1,
                   help="lines per clip (1 = one line, the old shape). More "
                        "than one gives a line-start head its negatives")
    p.set_defaults(run=lambda a: dataset.build(a.songs, a.out, a.spare,
                                               a.stem, a.pad, a.recut, a.ckpt, group=a.group))

    p = sub.add_parser("train", help="train the model")
    p.add_argument("--steps", type=int, default=20000)
    p.add_argument("--more", type=int, default=0,
                   help="carry on from the checkpoint for this many steps")
    p.add_argument("--data", default=str(dataset.DATA))
    p.add_argument("--dim", type=int, default=320)
    p.add_argument("--blocks", type=int, default=12)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--hold", type=float, default=0.08)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--lr", type=float, default=None)
    p.add_argument("--every", type=int, default=250)
    p.add_argument("--drop", type=float, default=0.2)
    p.add_argument("--kind", default="syncnet", choices=["syncnet", "wav2vec"],
                   help="syncnet trains this project's own small model from "
                        "noise; wav2vec fine-tunes a pretrained speech encoder")
    p.add_argument("--accum", type=int, default=1,
                   help="batches to accumulate before a step")
    p.add_argument("--large", action="store_true",
                   help="the 24-layer phoneme encoder instead of the base one")
    p.add_argument("--encoder", default="",
                   help=f"any wav2vec2 encoder on Hugging Face, by name. "
                        f"Multilingual at base size: {encoder.VOXPOPULI}")
    p.add_argument("--top", type=int, default=0,
                   help="train only this many top layers (0 trains them all)")
    p.add_argument("--lines", action="store_true",
                   help="also predict where a LYRIC LINE begins, as a third "
                        "task — needs a dataset cut with --group above 1, or "
                        "every clip holds exactly one line start and the head "
                        "learns the position instead of the sound")
    p.add_argument("--voice", action="store_true",
                   help="also predict WHERE ANYBODY IS SINGING, as an extra "
                        "boundary channel, labelled from the separated vocal "
                        "of the same clip. The coarse half of a coarse-to-fine "
                        "alignment needs evidence the character path does not "
                        "already hold, and on a mixture neither the loudness "
                        "curve nor the blank posterior supplies it")
    p.add_argument("--pitch", action="store_true",
                   help="also predict note height and note change from the "
                        "audio, as a second task — the head is discarded at "
                        "inference and only what it did to the encoder is kept")
    p.add_argument("--rebalance", action="store_true",
                   help="rebuild each training clip as its own vocal plus its "
                        "own accompaniment at 0.7-2x, from the sibling "
                        "-stem cut — the band at a level the model has to "
                        "learn to hear past, rather than a different song")
    p.add_argument("--distract", type=float, default=None,
                   help="how often a clip gets a DIFFERENT song mixed under "
                        "it (default from data.DISTRACT; 0 turns it off "
                        "without touching --rebalance)")
    p.add_argument("--freeze", type=int, default=800,
                   help="steps the head learns alone before the encoder joins")
    p.set_defaults(run=lambda a: train.run(
        a.steps, a.more, a.data, a.ckpt, a.dim, a.blocks, a.batch, a.hold,
        a.device, a.workers, a.every, a.lr, a.drop, kind=a.kind,
        accum=a.accum, freeze=a.freeze, large=a.large, top=a.top,
        pitch=a.pitch, lines=a.lines, encoder=a.encoder,
        rebalance=a.rebalance, distract=a.distract, voice=a.voice))

    p = sub.add_parser("bench", help="measure it on held-out songs")
    p.add_argument("--songs", type=int, default=12)
    p.add_argument("--name", action="append", default=None,
                   help="measure these songs instead of the held-out set")
    p.add_argument("--calibrate", action="store_true",
                   help="and store the standing bias in the checkpoint")
    p.add_argument("--spare", type=float, default=0.4)
    p.add_argument("--stem", action="store_true",
                   help="separate the vocal first (off by default)")
    p.add_argument("--no-report", action="store_true")
    p.add_argument("--by", default="",
                   help="only songs this person timed by hand, e.g. --by gc")
    # MEASURE WHAT SHIPS. These three used to default to 0.0 here while the
    # generator that writes the files defaults them to 2.0, 0.12 and 0.8 --
    # so `sync bench` with no flags measured an aligner nobody runs, and
    # nothing in a report said which of the two it had been. They are taken
    # from the generator now, the way --prior is taken from ctcalign, so the
    # two cannot drift apart again; the settings are written into the report.
    p.add_argument("--gate", type=float, default=None,
                   help="how many nats of blank bonus a silent frame gets, "
                        "from the audio's own energy — worth most on a "
                        "separated vocal, where quiet means nobody is singing "
                        "(default from generate.GATE)")
    p.add_argument("--attack", type=float, default=None,
                   help="seconds a word start may be pulled earlier onto the "
                        "nearest sung attack (0 leaves starts as the search "
                        "found them; default from generate.ATTACK)")
    p.add_argument("--floor", type=float, default=0.0,
                   help="the shortest a word may be, in seconds (0 = no "
                        "floor); stops a line being crushed to reach the next")
    p.add_argument("--sustain", type=float, default=None,
                   help="how far a word start may reach back onto the attack "
                        "that began a HELD note (0 = off; default from "
                        "generate.SUSTAIN)")
    p.add_argument("--all-held", dest="all_held", action="store_true",
                   help="every song held out by EITHER rule -- one hand's "
                        "gold split and the name hash together. 43 songs "
                        "rather than 17 or 30, which is what it takes to tell "
                        "a real change from a fresh run")
    p.add_argument("--refresh", action="store_true",
                   help="hear every song again instead of reading the "
                        "emissions kept in sync/jar/")
    p.add_argument("--prior", type=float, default=None,
                   help="how much of the model's own label prior to divide "
                        "out before searching (default from ctcalign.PRIOR)")
    p.add_argument("--uncrush", action="store_true",
                   help="second pass: re-solve each squeezed line together "
                        "with the line before it (off by default)")
    p.add_argument("--repace", action="store_true",
                   help="second pass: start a line again when it was given "
                        "more room than its syllables can fill")
    p.add_argument("--onattack", action="store_true",
                   help="start a line on the loudest attack it plausibly "
                        "begins on, when the one it began on is much weaker")
    p.set_defaults(run=lambda a: bench.run(a.ckpt, a.songs, a.device,
                                           a.stem, _shipped(a, "gate"),
                                           _shipped(a, "attack"), a.floor,
                                           a.prior if a.prior is not None
                                           else __import__("sync.ctcalign",
                                                           fromlist=["x"]).PRIOR,
                                           _shipped(a, "sustain"), a.spare,
                                           a.calibrate,
                                           a.name, report=not a.no_report,
                                           by=a.by, uncrush=a.uncrush,
                                           repace=a.repace,
                                           onattack=a.onattack,
                                           refresh=a.refresh,
                                           all_held=a.all_held))

    p = sub.add_parser("offsets", help="measure where each copy sits")
    p.add_argument("--songs", type=int, default=0,
                   help="only this many songs not measured before")
    p.add_argument("--spare", type=float, default=0.4)
    p.add_argument("--stem", action="store_true",
                   help="separate the vocal first (off by default)")
    p.set_defaults(run=lambda a: bench.offsets(a.ckpt, a.device,
                                               a.stem, a.spare, a.songs))

    p = sub.add_parser("ttml", help="write a synced lyric file")
    p.add_argument("song", nargs="?", default="")
    p.add_argument("--format", default="ttml",
                   choices=["ttml", "elrc", "lrc", "json", "text"])
    p.add_argument("--out", default=str(ROOT / "lyrics"))
    p.add_argument("--spare", type=float, default=0.4)
    # Three states, so --stem/--no-stem both mean something and the default is
    # neither: try the mixture, separate only if it reads badly.
    p.add_argument("--stem", dest="stem", action="store_true", default=None,
                   help="always separate the vocal first")
    p.add_argument("--no-stem", dest="stem", action="store_false",
                   help="never separate; align the mixture whatever it costs")
    p.add_argument("--sustain", dest="ttml_sustain", type=float, default=None,
                   help=f"how far a word start may reach back onto the attack "
                        f"that began a HELD note (default "
                        f"{generate.SUSTAIN}s; 0 turns it off)")
    p.add_argument("--uncrush", action="store_true",
                   help="re-time lines whose words were squeezed to reach the "
                        "next line the model was sure of (off: measured to "
                        "help the squeezed line and cost more elsewhere)")
    p.add_argument("--repace", action="store_true",
                   help="start a line again when it was given more room "
                        "than its syllables can fill")
    p.add_argument("--onattack", action="store_true",
                   help="start a line on the loudest attack it plausibly "
                        "begins on")
    p.add_argument("--lean", dest="lean", action="store_true", default=False,
                   help="square the file against its own sung attacks "
                        "(measured WORSE against hand timing: 0.068s -> 0.143s "
                        "— a person times a little after the attack)")
    p.add_argument("--fallback", default=None,
                   help="the stem-trained model to fall back to (default: the "
                        "'-stem' file beside --ckpt)")
    p.add_argument("--any-source", action="store_true",
                   help="allow a lyric that is not an spl upload")
    p.add_argument("--gate", type=float, default=None,
                   help=f"blank bonus for silent frames (default "
                        f"{generate.GATE}); 0 turns it off")
    p.add_argument("--attack", type=float, default=None,
                   help=f"seconds a word start may be pulled onto a sung "
                        f"attack (default {generate.ATTACK}); 0 turns it off")
    p.set_defaults(run=cmd_ttml)

    p = sub.add_parser("library", help="time every snapshotted lyric")
    p.add_argument("--out", default=str(ROOT / "lyrics/library"))
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--spare", type=float, default=0.4)
    p.add_argument("--redo", action="store_true",
                   help="write songs already done again")
    p.add_argument("--no-stem", dest="stem", action="store_false", default=True)
    p.add_argument("--gate", type=float, default=None)
    p.add_argument("--attack", type=float, default=None)
    p.set_defaults(run=lambda a: library.run(a.ckpt, a.out, a.limit, a.device,
                                             a.stem, a.spare, a.redo,
                                             a.gate, a.attack))

    p = sub.add_parser("status", help="what exists so far")
    p.set_defaults(run=cmd_status)

    args = ap.parse_args(argv)
    if args.ckpt is None:
        args.ckpt = str(_default_ckpt())
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
