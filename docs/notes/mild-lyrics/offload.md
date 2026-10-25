# `mild-lyrics/offload.py`

Comments lifted out of `mild-lyrics/offload.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

This module is newer than the two lifts, so everything here was written with it.


## module level

**line 42** — before `WORKERS = 2`

> Two, because the walk is what is being got out of the way and the walk's own
> heavy work is two things wide at a time -- one blend weighing letters while
> another waits on QQ. More workers would each cost a fork and would spend the
> time contending for the same disk and the same cores the window is drawing
> on, which is the problem rather than the fix.

**line 43** — before `FIRST_WAIT = 90.0`

> The first call to a pool may be waiting on a worker that is still starting,
> and on Windows a starting worker is importing lyrics_gui. The generous wait
> is for that one; everything after it is answered by a process that is
> already up, and 30 seconds is already ten times the worst blend measured.
>
> Neither is a deadline the answer depends on. A wait that runs out retires
> the pool and the work is done here instead, which is what would have
> happened anyway had there never been a pool.


## `_context`

**line 73** — before `names = ("fork", "forkserver", "spawn") if sys.platform != "win32" \`

> Found the hard way, and the reason this is not just `get_context()`. Both
> forkserver and spawn rebuild a worker by re-running the parent's MAIN
> MODULE, which for this program is lyrics_gui -- and a worker asked to do
> that never finished: `warm()` sat waiting on a child importing PyQt inside
> a harness that had, in turn, imported the window. fork inherits the
> interpreter instead and re-runs nothing at all.


## `warm`

**line 120** — before `with _lock:`

> Opt-in, and the `__main__` guard is why. A program without one would start a
> second copy of itself the first time a blend was weighed, under either of the
> methods that re-run the main module. Every entry point in this repository has
> the guard -- but the test scripts do not, and with this arrangement neither
> they nor any future script need think about it: a caller that has not asked
> for a pool has not got one, and does the work in its own process exactly as
> it always did.

**line 125** — before `pool.submit(_ping).result(FIRST_WAIT)`

> ProcessPoolExecutor starts its workers on the first submit, not when it is
> built, so without this the fork would land on the first blend of the first
> track -- which is the exact moment this module exists to keep clear. One
> ping moves it to startup.


## `call`

**line 144** — before `pool = _pool                      # only warm() builds one`

> Read under the lock and used outside it. A pool that retires between these
> two lines is not a problem: the submit raises, and the answer is worked out
> here.


## `_retire`

**line 161** — before `_off, _why = True, why`

> Once, not per call. A pool that has broken once will break again, and a
> program that tries a broken pool for every blend of every track pays the
> timeout each time instead of the work.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/offload.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Work that holds the interpreter, done somewhere it holds nobody up.
>
> A cold track runs the provider walk, and the walk is pure Python: it decrypts
> QQ's envelope and it diffs one document's letters against another's. Neither
> waits on anything, so neither ever lets the GIL go, and the thread that draws
> the words simply does not run. Measured on the real cold path -- attach to the
> player, forget the cache for the track that is up, ask for it again, and watch
> a 16ms timer -- the window went **1419ms** late, with nothing on its own side
> of the fence taking more than 41ms of that.
>
> So the work moves out of the process rather than being made cheaper. That
> distinction is the whole point of this module: the two functions sent through
> here are sent UNCHANGED, running the same code on the same interpreter, so
> nothing they decide can come out differently. `_shorter` in particular was
> tried both of the cheap ways first -- a line-level ceiling, and trimming the
> identical head and tail -- and both moved real answers, because what it
> returns is not a property of the two documents but of what difflib's greedy
> recursion happens to match. See docs/notes/TODO.md.
>
> What crosses the pipe is deliberately small. `_shorter` wants two documents
> but reads only their letters, so the letters go and the documents stay: about
> 6KB instead of megabytes. A round trip measured against doing it here is
> 0.6ms on 154ms of work.
>
> `forkserver` where there is one, because a child then inherits an interpreter
> that already has `lyric_sources` in it -- 0.3ms to import, against 45ms under
> `spawn`, which is what Windows gets. The server is forked once, and `warm()`
> exists so that it is forked from `main()` before the window has started any
> threads: forking a process that has threads in it is how a child ends up
> holding a lock nobody will ever release.
>
> Nothing here is required. If a pool cannot be built, or a call to one raises,
> or it is switched off with MILD_LYRICS_NO_POOL, the work is done in this
> process exactly as it was before -- slowly, and correctly.

### `_context`

**line 164** — from the docstring, `def _context():`

> How a worker is started, and why it is this way round.
>
> `fork` where there is one. The other two methods re-run the MAIN MODULE in
> every worker they start -- that is how they rebuild the state a fork would
> have inherited -- and this program's main module is lyrics_gui: sixteen
> thousand lines and the whole of PyQt, per worker. Measured trying it, a
> worker never finished importing it and warm() sat there waiting.
>
> fork inherits instead, so it re-runs nothing, costs milliseconds, and
> cannot hang on somebody else's import. The price is that forking a
> process which has threads in it gives the child one thread and all of the
> other threads' locks, held for ever by nobody -- which is why warm() is
> called from main() before the window is built, and says so.
>
> Windows has no fork and gets spawn, which does pay that import. It is paid
> once per worker inside warm(), at startup, rather than on the first blend
> of the first track.

### `warm`

**line 195** — from the docstring, `def warm() -> None:`

> Build the pool. Nothing uses one until somebody calls this.
>
> Opt-in on purpose, and it is the `__main__` guard that makes it so. Both
> start methods re-run the main module in the child, so a program without
> that guard would start a second copy of itself the first time a blend was
> weighed. Every entry point in this repository has one -- but the test
> scripts do not, and neither need ever wonder: a caller that has not asked
> for a pool does not get one, and does the work in its own process exactly
> as it did before.
>
> Called from main() before the window exists, so the fork that makes the
> server happens while this process is still one thread. Safe to call more
> than once and safe to never call at all.
>
> A worker is started here rather than left to appear on the first blend.
> ProcessPoolExecutor starts them lazily, and a starting worker re-runs the
> main module -- which for the window is lyrics_gui, PyQt and all. That is
> a second of import, and the whole point of this module is to keep seconds
> out of the first few of a track.
