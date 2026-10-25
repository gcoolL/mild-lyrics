"""Start a child program without a console window flashing up (Windows:
CREATE_NO_WINDOW and SW_HIDE). Elsewhere the identity function."""
from __future__ import annotations

import os
import subprocess

WIN = os.name == "nt"
# getattr rather than the attribute, because subprocess only defines it on
# Windows and this module is imported everywhere.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if WIN else 0


def hidden(**kw) -> dict:
    """`kw` with whatever it takes to keep a console off the screen added.

    Written as a filter over keyword arguments so a call site keeps its own
    timeout, capture_output, check and the rest unchanged -- the only edit a
    caller needs is to hand its arguments through here.
    """
    if not WIN:
        return kw
    kw["creationflags"] = int(kw.get("creationflags", 0)) | NO_WINDOW
    if "startupinfo" not in kw:
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        kw["startupinfo"] = info
    return kw


def run(*args, **kw):
    """subprocess.run, with no console window."""
    return subprocess.run(*args, **hidden(**kw))


def popen(*args, **kw):
    """subprocess.Popen, with no console window."""
    return subprocess.Popen(*args, **hidden(**kw))


def real_path(path) -> str:
    """`path` as another program sees it. The Microsoft Store's Python writes new files under
    AppData into its own package folder, which only it sees at the usual path; os.path.realpath
    finds the real one (Python's docs, using/windows). A file not made yet: its folder's."""
    p = os.fspath(path)
    if not WIN or "://" in p:
        return p
    if os.path.exists(p):
        return os.path.realpath(p)
    head, tail = os.path.split(p)
    return os.path.join(os.path.realpath(head), tail) if head and os.path.exists(head) else p
