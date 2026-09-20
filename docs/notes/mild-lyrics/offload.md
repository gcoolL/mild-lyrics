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
