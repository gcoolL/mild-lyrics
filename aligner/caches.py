#!/usr/bin/env python3
"""What this app has left on the disk, and how to get rid of it.

Everything here is derived. Nothing in the cache is the only copy of
anything -- art is re-fetched, lookups are re-asked, alignments are
re-run -- which is what makes clearing any of it safe, and is also why it
grows without anybody noticing: 900 MB of album art and animated covers
accumulates one song at a time and is never once in the way.

Two of the entries are the exception, and they are marked `keep`:

  * `aligned` is work this machine did. Re-running it costs minutes per
    song and a GPU, and on a machine without one it may not be repeatable
    at all.
  * `editor-history` is the backup net -- the copies taken before a
    document was replaced or a file written over. It is the one thing here
    that exists precisely because something else was lost.

`sources.json` is a third, quieter case: it pins WHICH copy of a track an
alignment was made against, so clearing it does not lose a timing but does
lose the reason two runs agreed. It is marked `keep` for that reason.

Qt is deliberately not imported. The player, the editor, doctor.py and the
command line all need this answer, and only two of them are a GUI.

    python3 caches.py              what is on the disk, and how big
    python3 caches.py --clear art  clear one by name
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]

import lyric_sources as LS  # noqa: E402


def _audio_dir() -> pathlib.Path:
    """Where fetched songs actually live, asked of the module that puts them
    there rather than guessed."""
    try:
        import local_align as LA
        return pathlib.Path(LA.AUDIO_DIR)
    except Exception:
        return _HERE.parent / "fetched"


def entries() -> list[dict]:
    """Every cache this app writes, whether or not it exists yet."""
    root = LS.cache_root()
    rows = [
        dict(key="sources", label="Lyric lookups", path=root / "sources",
             note="What each provider answered, so a track change does not "
                  "re-ask three servers that already said no. Kept for as "
                  "long as the song is still played -- an entry only ages "
                  "out after a month of not being heard."),
        dict(key="art", label="Album art", path=root / "art",
             note="Cover images, at the size they are drawn."),
        dict(key="motion", label="Animated covers", path=root / "motion",
             note="The moving covers, which are video and are the largest "
                  "thing here by a wide margin."),
        dict(key="fonts", label="Downloaded fonts", path=root / "fonts",
             note="Fonts fetched for the lyric display."),
        dict(key="aligned", label="Alignments made here", path=root / "aligned",
             keep=True,
             note="Timings this machine produced. Re-running them costs "
                  "minutes per song and wants a GPU."),
        dict(key="editor-history", label="Editor backups",
             path=root / "editor-history", keep=True,
             note="Copies taken before a document was replaced or a file "
                  "written over. The net under everything else."),
        dict(key="index", label="Track index", path=root / "index.json",
             note="What the player knows about the songs it has seen."),
        dict(key="tracks", label="Cached track list", path=root / "tracks.json",
             note="Track ids and names read out of the player's own cache."),
        dict(key="pins", label="Pinned audio sources", path=root / "sources.json",
             keep=True,
             note="Which copy of a track each alignment was made against. "
                  "Clearing it keeps the timings and loses the reason two "
                  "runs of the same song agreed."),
        dict(key="offsets", label="Measured offsets", path=root / "offsets.json",
             note="Per-track timing offsets measured against the audio."),
        # Not `root / "audio"`: the copies land in `local_align.AUDIO_DIR`,
        # which is `fetched/` beside the code, and always have. This row was
        # pointing at a directory nothing writes, so the largest thing on the
        # disk -- eight gigabytes on this machine -- was the one thing the
        # Storage dialog could not see or clear.
        dict(key="audio", label="Fetched audio", path=_audio_dir(),
             note="Copies of songs downloaded to align against, and to time "
                  "against in the editor. Capped at 8 GB, oldest dropped "
                  "first."),
        # Audio as well as pictures since the editor learned to PLAY the
        # separated vocal, which makes this the one row here that grows by
        # tens of megabytes a song rather than by kilobytes. Not `keep`:
        # every byte of it is re-derivable from the audio, at the cost of a
        # separation per song.
        dict(key="vocal-view", label="Separated vocals", path=root / "vocal-view",
             note="The demucs vocal for each song opened in the editor -- the "
                  "spectrogram drawn behind the words, and the stem itself, "
                  "to time against with the band turned down. Clearing it "
                  "costs a separation the next time a song is opened."),
        dict(key="eval-jar", label="Blend measurements", path=root / "eval-jar",
             note="What NetEase, QQ Music and Kugou answered for the songs "
                  "with a hand-timed reference, held still so a change to the "
                  "blends can be measured against the same documents twice. "
                  "Only present on a machine that has run eval_blends.py, and "
                  "it fetches them again."),
    ]
    for key, label, sub, note in (
            ("sync", "Sync checkpoints", "sync",
             "Trained models and their training state. Only present on a "
             "machine that has trained one."),
            ("dataset", "Training clips", "dataset",
             "Audio cut into clips for training."),
            ("dataset-raw", "Training clips (uncorrected)", "dataset-uncorrected",
             "The same clips before offset correction."),
            ("w2v", "Fine-tuned w2v", "w2v-singing",
             "The fine-tuned wav2vec checkpoint.")):
        path = LS.cache_root() / sub
        if path.exists():
            rows.append(dict(key=key, label=label, path=path, note=note,
                             keep=True, training=True))
    return rows


def cache_dir() -> pathlib.Path:
    """Where all of it lives, for anything that wants to say so."""
    return LS.cache_root()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# The file and key from_genius reads its token out of. Named there because
# that is where a provider needs them, and taken from there here so the two
# readers of one credential cannot drift apart.
CONFIG, GENIUS_KEY = LS.GENIUS_CONFIG, LS.GENIUS_KEY


def _config_files() -> tuple[pathlib.Path, ...]:
    """The settings file and the generation behind it.

    The player rotates gui.json to gui.json.bak on every write and reads the
    backup when the live file will not parse. A token cleared from one and
    left in the other is still a token on the disk, and one corrupted save
    away from coming back.
    """
    live = LS.config_root() / CONFIG
    return (live, live.with_suffix(".json.bak"))


def credentials() -> list[dict]:
    """What this copy is holding that identifies somebody.

    Two, and they are different in kind. The Genius token is typed in by a
    person, is theirs, and unlocks their account's rate limit -- handing a
    copy of this to somebody else hands them that. The Apple one is lifted
    out of the web player's own JavaScript, is the same key every visitor to
    music.apple.com is given, and belongs to nobody; it is here because it
    expires and re-fetching it means downloading three megabytes.

    Neither is ever written into the program files, so a checkout of this
    repository has never carried one. They are on the machine, which is
    exactly where a copy being passed on will not look.
    """
    import json
    cfg, token = _config_files()[0], ""
    for path in _config_files():
        try:
            got = str((json.loads(path.read_text(encoding="utf-8")) or {})
                      .get(GENIUS_KEY) or "")
        except Exception:
            continue
        if got:
            token, cfg = got, path
            break
    apple = cache_dir() / "apple-token.json"
    mxm = cache_dir() / "musixmatch-token.json"
    return [
        dict(key="genius", label="Genius API token", path=cfg,
             present=bool(token),
             note="Typed in by you, tied to your Genius account."),
        dict(key="apple", label="Apple Music key", path=apple,
             present=apple.exists(),
             note="Lifted from the web player's bundle; belongs to nobody "
                  "and re-fetches itself."),
        dict(key="musixmatch", label="Musixmatch app token", path=mxm,
             present=mxm.exists(),
             note="Handed out to anyone who asks as the Musixmatch app; "
                  "belongs to nobody. It re-fetches itself, but not often -- "
                  "the endpoint refuses for half an hour after a few asks."),
    ]


def forget() -> tuple[int, list[str]]:
    """Drop every stored credential. Returns (how many, what happened).

    The Genius token is removed from the settings file rather than the file
    being deleted -- everything else in there is preferences somebody spent
    time on, and losing a font size to clear a token is not a trade anybody
    asked for.
    """
    import json
    gone, said = 0, []
    for cfg in _config_files():
        try:
            got = json.loads(cfg.read_text(encoding="utf-8"))
            if got.get(GENIUS_KEY):
                got[GENIUS_KEY] = ""
                cfg.write_text(json.dumps(got, indent=1), encoding="utf-8")
                gone += 1
                said.append(f"Genius token cleared from {cfg.name}")
        except FileNotFoundError:
            continue
        except Exception as exc:                         # noqa: BLE001
            said.append(f"could not clear the Genius token in {cfg.name}: {exc}")
    for path, label in ((cache_dir() / "apple-token.json", "Apple Music key"),
                        (cache_dir() / "musixmatch-token.json",
                         "Musixmatch app token")):
        if not path.exists():
            continue
        try:
            path.unlink()
            gone += 1
            said.append(f"{label} forgotten")
        except Exception as exc:                         # noqa: BLE001
            said.append(f"could not forget the {label}: {exc}")
    if not said:
        said.append("nothing stored to forget")
    return gone, said


# --------------------------------------------------------------------------
def size(path: pathlib.Path) -> int:
    """Bytes on disk, walking a directory or stat-ing a file. Never raises."""
    try:
        if path.is_file():
            return path.stat().st_size
        if not path.is_dir():
            return 0
    except OSError:
        return 0
    total = 0
    for here, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += (pathlib.Path(here) / name).stat().st_size
            except OSError:
                pass
    return total


def count(path: pathlib.Path) -> int:
    """How many files, for the ones where the number means more than the size."""
    try:
        if path.is_file():
            return 1
        if not path.is_dir():
            return 0
    except OSError:
        return 0
    n = 0
    for _here, _dirs, files in os.walk(path, onerror=lambda _e: None):
        n += len(files)
    return n


def human(n: int) -> str:
    """A size somebody can read at a glance. 0 is spelled out as empty."""
    if n <= 0:
        return "empty"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def survey() -> list[dict]:
    """Every cache with its size and file count filled in, largest first."""
    rows = []
    for row in entries():
        got = dict(row)
        got["bytes"] = size(row["path"])
        got["files"] = count(row["path"])
        got["exists"] = row["path"].exists()
        got["human"] = human(got["bytes"])
        rows.append(got)
    return sorted(rows, key=lambda r: -r["bytes"])


_MEMO: dict = {}


def sizes(refresh: bool = False) -> dict:
    """key -> its surveyed row, computed once and kept until asked again.

    A survey stats tens of thousands of files. The player draws its menu many
    times a second and one of the rows is a size, so the walk happens when
    the menu opens and when something is cleared -- not on the way past.
    """
    if refresh or not _MEMO:
        _MEMO.clear()
        _MEMO.update({r["key"]: r for r in survey()})
    return _MEMO


def total() -> int:
    return sum(r["bytes"] for r in survey())


def clear(key: str) -> tuple[bool, int, str]:
    """Remove one cache by key. Returns (did anything, bytes freed, what).

    Never raises: a cache that will not delete is not a reason to take the
    window down with it, and the message is what the caller shows.
    """
    row = next((r for r in entries() if r["key"] == key), None)
    if row is None:
        return False, 0, f"no cache called {key!r}"
    path = row["path"]
    if not path.exists():
        return False, 0, f"{row['label']} was already empty"
    freed = size(path)
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    except Exception as exc:                             # noqa: BLE001
        return False, 0, f"could not clear {row['label']}: {exc}"
    _MEMO.clear()
    return True, freed, f"cleared {row['label']} — {human(freed)} freed"


def clear_all(include_kept: bool = False) -> tuple[int, list[str]]:
    """Clear the ordinary caches. The `keep` ones only when asked for."""
    freed, said = 0, []
    for row in entries():
        if row.get("keep") and not include_kept:
            continue
        ok, got, why = clear(row["key"])
        if ok:
            freed += got
            said.append(why)
    return freed, said


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clear", metavar="KEY",
                    help="clear one cache by key, or 'all'")
    ap.add_argument("--everything", action="store_true",
                    help="with --clear all, include the kept ones too")
    ap.add_argument("--forget", action="store_true",
                    help="drop every stored credential")
    args = ap.parse_args()

    if args.forget:
        _n, said = forget()
        for line in said:
            print(line)
        return 0

    if args.clear:
        if args.clear == "all":
            freed, said = clear_all(args.everything)
            for line in said:
                print(line)
            print(f"\n{human(freed)} freed")
            return 0
        ok, freed, why = clear(args.clear)
        print(why)
        return 0 if ok else 1

    rows = survey()
    print(f"Cache  {LS.cache_root()}\n")
    for row in rows:
        mark = "*" if row.get("keep") else " "
        files = (f"{row['files']:>6} file{'s' if row['files'] != 1 else ' '}"
                 if row["files"] else "            ")
        print(f" {mark} {row['key']:<14} {row['human']:>10}  {files}  "
              f"{row['label']}")
    print(f"\n    {'total':<14} {human(sum(r['bytes'] for r in rows)):>10}")
    if any(r.get("keep") for r in rows):
        print("\n  * worth a second thought before clearing — see --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
