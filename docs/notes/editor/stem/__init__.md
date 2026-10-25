# `editor/stem/__init__.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/stem/__init__.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The separated vocal, for the vocal view: demucs, and what is read off it.
>
> Optional. Everything in here stands on torch, torchaudio and demucs, which
> the rest of the program no longer needs, so nothing imports this until the
> vocal view is asked for -- and `available` says whether it can be, and why
> not, without importing any of it.

### `spare_cores`

**line 28** — from the docstring, `def spare_cores(keep: int = 2):`

> Let torch use all but `keep` cores while the body runs.
>
> Torch takes every core it is given, and a separation on the CPU runs for
> minutes: the window and the audio player it shares the machine with are
> starved for all of them. The count is put back when the body is done, and
> is only ever lowered, so a machine with few cores is not asked for more
> than torch would have used.
