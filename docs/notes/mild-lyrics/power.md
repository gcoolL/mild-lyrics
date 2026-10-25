# `mild-lyrics/power.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/power.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Whether this machine has a battery, is running on it, how full it is, or
> is saving power.
>
> Read from the system each platform's own way -- sysfs on Linux,
> GetSystemPowerStatus on Windows, pmset on macOS -- and kept for TTL seconds,
> so the window can ask on a timer without the asking costing anything.
> Everything answers "no battery" where it cannot tell, which leaves the
> window exactly as it was before this existed.
