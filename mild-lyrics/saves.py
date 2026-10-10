"""Where the TTMLs this program writes are kept, and who wrote them.

One folder beside the program, with two rooms in it:

    lyrics/fetched/   what the player saved off a song it fetched
    lyrics/made/      what somebody timed themselves, in the editor

They are split because they are not the same thing, and the difference is
only obvious while you are holding them. A file the player wrote is a copy of
a document somebody else made -- a community sync, Apple Music's, a blend --
kept because it was worth keeping. A file the editor wrote is the reader's
own work, and it is the one that cannot be fetched again. Left in one heap,
and both named "Artist - Title.ttml", the only way to tell them apart is to
open them and look at the timings.

They used to land loose in the program folder, which is how this checkout
came to have eighty TTMLs sitting next to lyrics_gui.py.

Both rooms are made when the editor starts and again whenever either program
saves, rather than once at install: a folder somebody deleted between runs is
not a reason for a save to fail.

THE PLAYER'S ROOM CAN BE POINTED SOMEWHERE ELSE. Settings ▸ Storage in the
player carries a row for the downloads, and the choice is kept in the
player's own settings file -- the same gui.json it writes everything else to.
It is read back from there rather than handed in, because the player is the
one that saves into that room. An entry that is not there, or is not an
absolute path, is the folder beside the program, which is where these went
before there was anywhere to change it.

The editor's room is NOT movable this way: where a piece of timed work is
written is the writer's call, made with Save as at the moment they make it,
and a setting that pinned it in advance would be answering a question that is
not the settings' to answer. It defaults beside the program and stays there.
"""

from __future__ import annotations

import json
import pathlib
import sys

HOME = pathlib.Path(__file__).resolve().parent.parent
LYRICS = HOME / "lyrics"

PLAYER = LYRICS / "fetched"
EDITOR = LYRICS / "made"

# The key the player's Settings ▸ Storage writes, read back here.
FETCHED_KEY = "save_fetched_dir"


def _settings() -> dict:
    """The player's settings file, for the two folders it can point elsewhere.

    Read here rather than handed in because the choice belongs to neither
    program alone: it is set once, in the player, and the editor reads the
    same answer. lyric_sources owns the path of that file -- it walks the
    same platform directories lyrics_gui.app_dir does -- and is imported
    lazily so this module stays importable on its own. Any failure, including
    a settings file that is simply not there yet, is the default.
    """
    try:
        here = str(pathlib.Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import lyric_sources as LS
        live = LS.config_root() / "gui.json"
    except Exception:                                    # noqa: BLE001
        return {}
    for path in (live, live.with_suffix(".json.bak")):
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                return got
        except Exception:                                # noqa: BLE001
            continue
    return {}


def chosen(key: str, default: pathlib.Path) -> pathlib.Path:
    """The folder set for one room, or the default beside the program.

    Only an absolute path is honoured. An empty one is "never set", and a
    relative one made up by hand would lean on a working directory neither
    program controls -- the very thing the folders beside the program were
    introduced to stop mattering -- so both are the default.
    """
    want = str(_settings().get(key) or "").strip()
    if not want:
        return default
    try:
        path = pathlib.Path(want).expanduser()
    except Exception:                                    # noqa: BLE001
        return default
    return path if path.is_absolute() else default


def _made(path: pathlib.Path) -> pathlib.Path:
    """The folder, made if it is not there. Never raises: the caller is about
    to write a file and will report what happens then, in the words of the
    thing it was actually trying to do."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def from_player() -> pathlib.Path:
    """Where the player keeps what it saved."""
    return _made(chosen(FETCHED_KEY, PLAYER))


def from_editor() -> pathlib.Path:
    """Where the editor keeps what was timed in it.

    Not a setting: the editor offers this as the suggested place and the
    writer picks the file when they save. See the module docstring.
    """
    return _made(EDITOR)


def ensure() -> pathlib.Path:
    """Both rooms, made. Called when the editor opens, so that somebody who
    goes looking for the folder finds it before they have saved anything."""
    from_player()
    return from_editor()
