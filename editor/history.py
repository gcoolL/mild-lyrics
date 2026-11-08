"""Undo snapshots the garbage collector does not have to walk: the newest LIVE
stay documents, older ones pickled bytes. Notes:
docs/notes/editor/history.md."""
from __future__ import annotations

import pickle

from . import model as M

LIVE = 8


class Kept:
    """A snapshot put away as bytes; remote edits wait in `later`."""

    __slots__ = ("blob", "later")

    def __init__(self, doc) -> None:
        self.blob = pickle.dumps(doc, pickle.HIGHEST_PROTOCOL)
        self.later: list = []


def put_away(stack: list, live: int = LIVE) -> None:
    """Pickle the snapshot that has just fallen out of the live few. A shared
    one (model.snapshot) stays: it holds little of its own, and pickling it
    copied the whole song on every tap."""
    i = len(stack) - live - 1
    if (i >= 0 and not isinstance(stack[i], Kept)
            and not stack[i].__dict__.get("_shared")):
        stack[i] = Kept(stack[i])


def take(snap):
    """The document a snapshot stands for, with any waiting edits applied."""
    from . import collab as C
    if not isinstance(snap, Kept):
        if snap.__dict__.get("_shared"):
            M.unshare(snap)
            for ops in snap.__dict__.pop("_later", []):
                C.apply(snap, ops)
        return snap
    doc = pickle.loads(snap.blob)
    for ops in snap.later:
        C.apply(doc, ops)
    return doc


def apply(snap, ops: list) -> None:
    """collab.apply for a snapshot of either kind."""
    if isinstance(snap, Kept):
        snap.later.append(list(ops))
        return
    if snap.__dict__.get("_shared"):
        # Its lines are other snapshots' too: the edits wait for take().
        snap.__dict__.setdefault("_later", []).append(list(ops))
        return
    from . import collab as C
    C.apply(snap, ops)
