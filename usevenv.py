"""Restart a launcher under the project's .venv, when there is one and this is not it.

mild-setup.py can put the packages in .venv, but a double-clicked .pyw, a
desktop shortcut or a mild-lyrics:// link starts whatever Python Windows or
the shortcut names. This makes all of them land in the venv's interpreter.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WIN = os.name == "nt"
_GUARD = "MILD_VENV_HOPPED"


def _target() -> pathlib.Path | None:
    """The venv interpreter to restart with, or None to stay in this one."""
    if os.environ.get(_GUARD):
        return None
    try:
        if pathlib.Path(sys.prefix).resolve() == VENV.resolve():
            return None
    except OSError:
        return None
    bindir = VENV / ("Scripts" if WIN else "bin")
    # pythonw from pythonw, so a double-click still opens no console.
    windowless = WIN and pathlib.Path(sys.executable).stem.lower() == "pythonw"
    exe = bindir / (("pythonw.exe" if windowless else "python.exe") if WIN
                    else "python3")
    if not exe.exists():                # also false for a dangling symlink
        return None
    if WIN and not _base_present():
        return None
    return exe


def _base_present() -> bool:
    """A Windows venv's python.exe is a stub; its real one is pyvenv.cfg's home."""
    try:
        for line in (VENV / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip().lower() == "home":
                return (pathlib.Path(value.strip()) / "python.exe").exists()
    except OSError:
        pass
    return False


def hop(script: str) -> None:
    """Re-run `script` with the venv's interpreter and exit, or return to carry on."""
    exe = _target()
    if exe is None:
        return
    env = dict(os.environ, **{_GUARD: "1"})
    argv = [str(exe), str(pathlib.Path(script).resolve()), *sys.argv[1:]]
    if WIN:
        # No real exec on Windows: wait, so a terminal run keeps its prompt
        # until the app is done, and pass the exit code on.
        try:
            raise SystemExit(subprocess.call(argv, env=env))
        except OSError:
            return
    try:
        os.execve(argv[0], argv, env)
    except OSError:
        return
