# `usevenv.py`

## 2026-10-14 — the venv question on Windows, and using it

`mild-setup.py` only offered `.venv` on a PEP 668 (externally managed)
Python, and Windows Pythons never are, so Windows users were never asked:
installs went to `--user`. `install_plan` now asks on every Python that is
not already in a venv, and still falls back to `--user` if the answer is no.

Making the venv was not enough by itself. Every way of starting the app
(a double-clicked `.pyw`, doctor's shortcuts, the `mild-lyrics://` handler,
the updater's restart) runs the Python it was started with or the Python
Windows ties to `.pyw`, and none of those is the venv. So both `.pyw`
launchers call `usevenv.hop` before importing anything. It restarts the
script under `.venv`'s interpreter. On Linux it is an `execve`. On Windows
it is a child process that the parent waits on, since Windows has no real
exec: `pythonw` stays `pythonw`, and the exit code is passed on.
`MILD_VENV_HOPPED` stops it looping.

When there is no `.venv`, or its base Python is gone, nothing changes: on
Linux the `bin/python3` symlink dangles, and on Windows `pyvenv.cfg`'s
`home` has no `python.exe`. The launcher then carries on in the Python it
was started with, as before.

Tested on Linux with a real venv, including a broken base. The Windows
branches were only run in simulation (paths and `pyvenv.cfg`), never on
Windows.
