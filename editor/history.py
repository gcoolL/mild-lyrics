"""Undo snapshots the garbage collector does not have to walk.

The newest LIVE stay as documents; older ones are kept as pickled bytes.
Eighty live copies of a long song are ~185k objects, and every full
collection walked them all: 40-75 ms pauses while tapping. See
docs/notes/editor/history.md.
"""
from __future__ import annotations

import pickle

LIVE = 8


class Kept:
    """A snapshot put away as bytes; remote edits wait in `later`."""

    __slots__ = ("blob", "later")

    def __init__(self, doc) -> None:
        self.blob = pickle.dumps(doc, pickle.HIGHEST_PROTOCOL)
        self.later: list = []


def put_away(stack: list, live: int = LIVE) -> None:
    """Pickle the snapshot that has just fallen out of the live few."""
    i = len(stack) - live - 1
    if i >= 0 and not isinstance(stack[i], Kept):
        stack[i] = Kept(stack[i])


def take(snap):
    """The document a snapshot stands for, with any waiting edits applied."""
    if not isinstance(snap, Kept):
        return snap
    from . import collab as C
    doc = pickle.loads(snap.blob)
    for ops in snap.later:
        C.apply(doc, ops)
    return doc


def apply(snap, ops: list) -> None:
    """collab.apply for a snapshot of either kind."""
    if isinstance(snap, Kept):
        snap.later.append(list(ops))
        return
    from . import collab as C
    C.apply(snap, ops)
