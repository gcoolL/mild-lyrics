"""Where this program's TTMLs go: lyrics/fetched/ for what the player saved,
lyrics/made/ for what somebody timed in the editor."""

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
