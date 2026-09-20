#!/usr/bin/env python3
"""Teach the aligner from the songs you have played, start to finish.

    ./learn.py                      # the whole thing, unattended
    ./learn.py --songs 400          # gather more first
    ./learn.py --skip-build         # use the dataset already on disk
    ./learn.py --steps 6000         # train for longer
    ./learn.py --status             # what happened last time

One command, because the process is five stages that each fail differently and
running them by hand is how a night gets lost to a stage that silently did
nothing. Every stage here refuses to be silent: it says what it did, what it
skipped and why, and it stops rather than continuing on a broken input.

The stages:

  1. gather     every played song with word-synced lyrics becomes clips, with
                its audio checked against its own words first
  2. hold back  whole songs, chosen by a hash of the name so the set does not
                drift as the cache grows, and never the same song twice under
                two track ids
  3. measure    the held-back songs with the stock model
  4. train      the rest
  5. measure    the same songs again, and compare only songs both passes did

What it cannot do is decide whether the answer is worth having. The comparison
it prints is honest about its own limits -- see the note it writes at the end.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import lyric_sources as LS      # noqa: E402

DATA = LS.cache_root() / "dataset"
TUNED = LS.cache_root() / "w2v-singing"
REPORT = ROOT / "REPORT.md"


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def spotify_is_up() -> bool:
    """The cache and the metadata both come from a running Spotify."""
    try:
        from spotify_dom import connect
        return connect(9222, "spotify") is not None
    except Exception:
        return False


def dataset_size() -> tuple[int, int]:
    """(songs, clips) on disk. Songs, not manifest rows -- they differ."""
    manifest = DATA / "manifest.jsonl"
    if not manifest.exists():
        return 0, 0
    names, clips = set(), 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        names.add(row.get("name"))
        clips += len(row.get("lines") or [])
    return len(names), clips


def status() -> int:
    songs, clips = dataset_size()
    print(f"dataset   {songs} songs, {clips} clips in {DATA}")
    print(f"model     {'trained, in ' + str(TUNED) if TUNED.exists() else 'not trained yet'}")
    if REPORT.exists():
        print(f"report    {REPORT}")
        for line in REPORT.read_text(encoding="utf-8").splitlines()[:8]:
            if line.strip():
                print(f"          {line}")
    else:
        print("report    none yet")
    kept = sorted((ROOT / "reports").glob("REPORT-*.md")) if (ROOT / "reports").exists() else []
    print(f"history   {len(kept)} earlier report(s)")
    return 0


def stage(name: str, argv: list[str]) -> bool:
    """Run one stage as its own process. False if it failed."""
    say(f"=== {name}")
    got = subprocess.run([sys.executable] + argv, cwd=HERE)
    if got.returncode != 0:
        say(f"{name} failed (exit {got.returncode})")
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Teach the aligner from your own listening.")
    ap.add_argument("--songs", type=int, default=200,
                    help="how many new songs to add to the dataset")
    ap.add_argument("--steps", type=int, default=3000,
                    help="training steps")
    ap.add_argument("--skip-build", action="store_true",
                    help="use the dataset already on disk")
    ap.add_argument("--status", action="store_true",
                    help="say what happened last time and stop")
    ap.add_argument("--spare", type=float, default=0.4,
                    help="GB of VRAM to leave for everything else")
    args = ap.parse_args()

    if args.status:
        return status()

    say("teaching the aligner from your own listening")
    songs, clips = dataset_size()
    say(f"starting with {songs} songs, {clips} clips already gathered")

    if not spotify_is_up():
        say("Spotify is not reachable on port 9222.")
        say("  Start Spotify (with Spicetify) and try again -- the lyrics and")
        say("  the track lengths both come from it.")
        return 1

    if not args.skip_build:
        if not stage(f"gathering up to {args.songs} songs",
                     ["build_dataset.py", "--songs", str(args.songs),
                      "--spare", str(args.spare)]):
            return 1
        songs, clips = dataset_size()
        say(f"dataset now {songs} songs, {clips} clips")

    if songs < 20:
        say(f"only {songs} songs -- not enough to learn anything from.")
        say("  Play more music with word-synced lyrics and run this again.")
        return 1

    env_steps = ["--steps", str(args.steps)] if args.steps != 3000 else []
    if not stage("holding songs back, measuring, training, measuring again",
                 ["run_pipeline.py"] + env_steps):
        return 1

    say(f"done -- the report is at {REPORT}")
    say("Read it with this in mind: after the anchor stage was removed the")
    say("held-out songs align at 0.05-0.25s, and the references they are")
    say("measured against carry their own error at that scale. A small")
    say("difference between the two passes is inside that. What the aligner")
    say("still gets badly wrong is a wrong recording, which no amount of")
    say("training fixes -- the report flags those separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
