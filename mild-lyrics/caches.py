#!/usr/bin/env python3
"""What this app has left on the disk, and how to get rid of it.
All of it is derived except the `keep` entries. No Qt here.
Run: python3 caches.py [--clear KEY] [--everything] [--forget]"""
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
    """Where fetched songs actually live: asked of the module that puts them
    there once it is loaded, and the same path it would say otherwise --
    importing it just to ask cost 3.6MB at startup (2026-10-17)."""
    LA = sys.modules.get("local_align")
    try:
        if LA is not None:
            return pathlib.Path(LA.AUDIO_DIR)
    except Exception:
        pass
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
        dict(key="spicy", label="Spicy Lyrics", path=root / "spicy",
             note="What Spicy Lyrics answered for each track, kept by the "
                  "same rule as the other lookups: a month from the last "
                  "time the song was played, six hours for a track it has "
                  "nothing for. Clearing it also empties the song list the "
                  "search offers, which is built from it."),
        dict(key="art", label="Album art", path=root / "art",
             note="Cover images, at the size they are drawn."),
        dict(key="motion", label="Animated covers", path=root / "motion",
             note="The moving covers, which are video and are the largest "
                  "thing here by a wide margin."),
        dict(key="fonts", label="Downloaded fonts", path=root / "fonts",
             note="Fonts fetched for the lyric display."),
        dict(key="editor-history", label="Editor backups",
             path=root / "editor-history", keep=True,
             note="Copies taken before a document was replaced or a file "
                  "written over. The net under everything else."),
        dict(key="index", label="Track index", path=root / "index.json",
             note="What the player knows about the songs it has seen."),
        dict(key="tracks", label="Cached track list", path=root / "tracks.json",
             note="Track ids and names for the songs a lyric is held for."),
        dict(key="pins", label="Pinned audio sources", path=root / "sources.json",
             keep=True,
             note="Which copy of a track each alignment was made against. "
                  "Clearing it keeps the timings and loses the reason two "
                  "runs of the same song agreed."),
        dict(key="offsets", label="Measured offsets", path=root / "offsets.json",
             note="Per-track timing offsets measured against the audio."),
        dict(key="audio", label="Fetched audio", path=_audio_dir(),
             note="Copies of songs downloaded to align against, and to time "
                  "against in the editor. Capped at 8 GB, oldest dropped "
                  "first."),
        dict(key="eval-jar", label="Blend measurements", path=root / "eval-jar",
             note="What NetEase, QQ Music and Kugou answered for the songs "
                  "with a hand-timed reference, held still so a change to the "
                  "blends can be measured against the same documents twice. "
                  "Only present on a machine that has run eval_blends.py, and "
                  "it fetches them again."),
    ]
    return rows


def cache_dir() -> pathlib.Path:
    """Where all of it lives, for anything that wants to say so."""
    return LS.cache_root()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
CONFIG, GENIUS_KEY = LS.GENIUS_CONFIG, LS.GENIUS_KEY


def _config_files() -> tuple[pathlib.Path, ...]:
    """The settings file and the backup generation behind it (gui.json.bak),
    since a token left in either is still on the disk."""
    live = LS.config_root() / CONFIG
    return (live, live.with_suffix(".json.bak"))


_TOKENS: dict = {}


def _token_in(path: pathlib.Path) -> str:
    """The Genius token a settings file holds, re-read only when the file
    changed. Raises where the file is missing or does not parse."""
    import json
    st = path.stat()
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _TOKENS.get(path)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    got = str((json.loads(path.read_text(encoding="utf-8")) or {})
              .get(GENIUS_KEY) or "")
    _TOKENS[path] = (stamp, got)
    return got


def credentials() -> list[dict]:
    """What this copy holds that identifies somebody: the Genius token, a
    secret Spicy key, the Apple and Musixmatch keys. None is ever in the
    program files."""
    cfg, token = _config_files()[0], ""
    for path in _config_files():
        try:
            got = _token_in(path)
        except Exception:
            continue
        if got:
            token, cfg = got, path
            break
    spicy = LS.SPICY_KEY_FILE
    apple = cache_dir() / "apple-token.json"
    mxm = cache_dir() / "musixmatch-token.json"
    fm = LS.config_root() / "lastfm.json"
    return [
        dict(key="genius", label="Genius API token", path=cfg,
             present=bool(token),
             note="Typed in by you, tied to your Genius account."),
        dict(key="spicy", label="Spicy Lyrics key", path=spicy,
             present=spicy.exists(),
             note="The key this copy sends to Spicy Lyrics. A secret one "
                  "(sl_sk_) is your application's and is worth as much as "
                  "the Genius token; a publishable one (sl_pk_) is public by "
                  "design."),
        dict(key="spotify_session", label="Spotify session token",
             path=LS.SPOTIFY_SESSION, present=LS.SPOTIFY_SESSION.exists(),
             note="Taken from your signed-in Spotify desktop app for Spotify "
                  "lookup; yours, and good for about an hour."),
        dict(key="apple", label="Apple Music key", path=apple,
             present=apple.exists(),
             note="Lifted from the web player's bundle; belongs to nobody "
                  "and re-fetches itself."),
        dict(key="lastfm", label="Last.fm session", path=fm, present=fm.exists(),
             note="Made when you allowed Mild Lyrics on Last.fm; scrobbles "
                  "to your account until you sign out."),
        dict(key="musixmatch", label="Musixmatch app token", path=mxm,
             present=mxm.exists(),
             note="Handed out to anyone who asks as the Musixmatch app; "
                  "belongs to nobody. It re-fetches itself, but not often -- "
                  "the endpoint refuses for half an hour after a few asks."),
    ]


def forget() -> tuple[int, list[str]]:
    """Drop every stored credential; returns (how many, what happened). The
    Genius token is removed from the settings, not the whole file."""
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
    for path, label in ((LS.SPICY_KEY_FILE, "Spicy Lyrics key"),
                        (LS.SPOTIFY_SESSION, "Spotify session token"),
                        (LS.config_root() / "lastfm.json", "Last.fm session"),
                        (cache_dir() / "apple-token.json", "Apple Music key"),
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
def measure(path: pathlib.Path) -> tuple[int, int]:
    """(bytes, files) under a directory, or for one file, in one walk. Never
    raises; counts the way os.walk does."""
    try:
        if path.is_file():
            return path.stat().st_size, 1
        if not path.is_dir():
            return 0, 0
    except OSError:
        return 0, 0
    total = n = 0
    todo = [str(path)]
    while todo:
        try:
            it = os.scandir(todo.pop())
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    is_dir = False
                if is_dir:
                    if not entry.is_symlink():
                        todo.append(entry.path)
                    continue
                n += 1
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    return total, n


def size(path: pathlib.Path) -> int:
    """Bytes on disk, walking a directory or stat-ing a file. Never raises."""
    return measure(path)[0]


def count(path: pathlib.Path) -> int:
    """How many files, for the ones where the number means more than the size."""
    return measure(path)[1]


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
        got["bytes"], got["files"] = measure(row["path"])
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
