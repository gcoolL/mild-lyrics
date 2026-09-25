"""The TTML Editor: write the words, then place them in time.

Everything here is a *tool*, not a player. It reads and writes the same
document shape the rest of Mild Lyrics passes around -- the Spicy Lyrics
document, with `Content` a list of lines, each with a `Lead` group of
syllables and any number of `Background` ones -- so a file edited here is a
file the player can already draw, and no format has to be invented for it.
"""

# ---------------------------------------------------------------------------
# The synchroniser this editor auto-times with is the `sync` package, and it
# does not live in this repository: it is training code and checkpoints, and
# it was moved out with the rest of what is not the program (see the README).
# autotime and vocalmap import it inside the functions that need it, so the
# editor opens and edits perfectly well without it -- what it loses is the
# auto-timing and the vocal map.
#
# Looked for beside the checkout as well as inside it, so a copy kept next
# door goes on working. Nothing is imported here; only the path is made
# ready, once, for whichever module asks first.
import pathlib as _pathlib  # noqa: E402
import sys as _sys  # noqa: E402

_root = _pathlib.Path(__file__).resolve().parent.parent
for _where in (_root, _root.parent / f"{_root.name}-archive"):
    if (_where / "sync").is_dir() and str(_where) not in _sys.path:
        _sys.path.append(str(_where))
        break
del _pathlib, _sys, _root, _where
