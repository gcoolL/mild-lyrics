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

The player's room can be moved from Settings ▸ Storage; the editor's cannot,
because where timed work goes is decided with Save as when it is saved.
"""

from __future__ import annotations

import pathlib

HOME = pathlib.Path(__file__).resolve().parent.parent
LYRICS = HOME / "lyrics"

PLAYER = LYRICS / "fetched"
EDITOR = LYRICS / "made"


def chosen(want: str) -> pathlib.Path:
    """The player's room as set, or the default for an empty or relative
    path -- a relative one would lean on whatever the working directory is."""
    want = str(want or "").strip()
    try:
        path = pathlib.Path(want).expanduser()
    except RuntimeError:
        return PLAYER
    return path if want and path.is_absolute() else PLAYER


def _made(path: pathlib.Path) -> pathlib.Path:
    """The folder, made if it is not there. Never raises: the caller is about
    to write a file and will report what happens then, in the words of the
    thing it was actually trying to do."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def from_player(want: str = "") -> pathlib.Path:
    """Where the player keeps what it saved: `want`, the Settings ▸ Storage
    choice, when it is an absolute path."""
    return _made(chosen(want))


def from_editor() -> pathlib.Path:
    """Where the editor keeps what was timed in it."""
    return _made(EDITOR)


def ensure() -> pathlib.Path:
    """Both rooms, made. Called when the editor opens, so that somebody who
    goes looking for the folder finds it before they have saved anything."""
    from_player()
    return from_editor()
