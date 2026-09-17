"""Work that holds the interpreter, done somewhere it holds nobody up.

A cold track runs the provider walk, and the walk is pure Python: it decrypts
QQ's envelope and it diffs one document's letters against another's. Neither
waits on anything, so neither ever lets the GIL go, and the thread that draws
the words simply does not run. Measured on the real cold path -- attach to the
player, forget the cache for the track that is up, ask for it again, and watch
a 16ms timer -- the window went **1419ms** late, with nothing on its own side
of the fence taking more than 41ms of that.

So the work moves out of the process rather than being made cheaper. That
distinction is the whole point of this module: the two functions sent through
here are sent UNCHANGED, running the same code on the same interpreter, so
nothing they decide can come out differently. `_shorter` in particular was
tried both of the cheap ways first -- a line-level ceiling, and trimming the
identical head and tail -- and both moved real answers, because what it
returns is not a property of the two documents but of what difflib's greedy
recursion happens to match. See docs/notes/TODO.md.

What crosses the pipe is deliberately small. `_shorter` wants two documents
but reads only their letters, so the letters go and the documents stay: about
6KB instead of megabytes. A round trip measured against doing it here is
0.6ms on 154ms of work.

`forkserver` where there is one, because a child then inherits an interpreter
that already has `lyric_sources` in it -- 0.3ms to import, against 45ms under
`spawn`, which is what Windows gets. The server is forked once, and `warm()`
exists so that it is forked from `main()` before the window has started any
threads: forking a process that has threads in it is how a child ends up
holding a lock nobody will ever release.

Nothing here is required. If a pool cannot be built, or a call to one raises,
or it is switched off with MILD_LYRICS_NO_POOL, the work is done in this
process exactly as it was before -- slowly, and correctly.
"""
from __future__ import annotations

import os
import sys
import threading

WORKERS = 2
FIRST_WAIT = 90.0
WAIT = 30.0

_lock = threading.Lock()
_pool = None
_off = bool(os.environ.get("MILD_LYRICS_NO_POOL"))
_why = "switched off" if _off else ""


def _context():
    """How a worker is started, and why it is this way round.

    `fork` where there is one. The other two methods re-run the MAIN MODULE in
    every worker they start -- that is how they rebuild the state a fork would
    have inherited -- and this program's main module is lyrics_gui: sixteen
    thousand lines and the whole of PyQt, per worker. Measured trying it, a
    worker never finished importing it and warm() sat there waiting.

    fork inherits instead, so it re-runs nothing, costs milliseconds, and
    cannot hang on somebody else's import. The price is that forking a
    process which has threads in it gives the child one thread and all of the
    other threads' locks, held for ever by nobody -- which is why warm() is
    called from main() before the window is built, and says so.

    Windows has no fork and gets spawn, which does pay that import. It is paid
    once per worker inside warm(), at startup, rather than on the first blend
    of the first track.
    """
    import multiprocessing as mp

    names = ("fork", "forkserver", "spawn") if sys.platform != "win32" \
        else ("spawn",)
    for name in names:
        try:
            return mp.get_context(name)
        except Exception:                                # noqa: BLE001
            continue
    return None


def _build():
    """A pool, or None and never again."""
    global _pool, _off, _why
    if _off or _pool is not None:
        return _pool
    try:
        from concurrent.futures import ProcessPoolExecutor

        ctx = _context()
        _pool = ProcessPoolExecutor(max_workers=WORKERS, mp_context=ctx)
    except Exception as e:                               # noqa: BLE001
        _off, _why = True, f"{e.__class__.__name__}: {e}"
        _pool = None
    return _pool


def warm() -> None:
    """Build the pool. Nothing uses one until somebody calls this.

    Opt-in on purpose, and it is the `__main__` guard that makes it so. Both
    start methods re-run the main module in the child, so a program without
    that guard would start a second copy of itself the first time a blend was
    weighed. Every entry point in this repository has one -- but the test
    scripts do not, and neither need ever wonder: a caller that has not asked
    for a pool does not get one, and does the work in its own process exactly
    as it did before.

    Called from main() before the window exists, so the fork that makes the
    server happens while this process is still one thread. Safe to call more
    than once and safe to never call at all.

    A worker is started here rather than left to appear on the first blend.
    ProcessPoolExecutor starts them lazily, and a starting worker re-runs the
    main module -- which for the window is lyrics_gui, PyQt and all. That is
    a second of import, and the whole point of this module is to keep seconds
    out of the first few of a track.
    """
    with _lock:
        pool = _build()
    if pool is None:
        return
    try:
        pool.submit(_ping).result(FIRST_WAIT)
    except Exception as e:                               # noqa: BLE001
        _retire(f"{e.__class__.__name__}: {e}")


def _ping() -> bool:
    """Nothing, done in a worker, so that there is a worker."""
    return True


def call(fn, *args):
    """fn(*args), in another process where there is one and here where not.

    `fn` has to be a module-level function and the arguments have to pickle,
    which is what keeps the two sent through here small and plain.
    """
    if _off:
        return fn(*args)
    with _lock:
        pool = _pool                      # only warm() builds one
        first = pool is not None and not getattr(pool, "_mild_used", False)
    if pool is None:
        return fn(*args)
    try:
        out = pool.submit(fn, *args).result(FIRST_WAIT if first else WAIT)
    except Exception as e:                               # noqa: BLE001
        _retire(f"{e.__class__.__name__}: {e}")
        return fn(*args)
    pool._mild_used = True
    return out


def _retire(why: str) -> None:
    """Stop using a pool that has let us down, and go back to doing it here."""
    global _pool, _off, _why
    with _lock:
        _off, _why = True, why
        pool, _pool = _pool, None
    if pool is not None:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:                                # noqa: BLE001
            pass


def state() -> dict:
    """What doctor.py and the tests ask."""
    return {"on": not _off, "built": _pool is not None, "why": _why,
            "workers": WORKERS}


def shutdown() -> None:
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:                                # noqa: BLE001
            pass
