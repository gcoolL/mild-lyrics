"""Start a child program without a console window flashing up in front of it.

Only Windows has anything to do here. Both launchers are .pyw files, which
Windows binds to pythonw.exe -- no console -- and that is exactly what makes
the problem: a process with no console of its own gets a BRAND NEW one when
it starts a console program, and Windows draws that console on top of
whatever the user was looking at. So fetching a song's audio in the editor
put a black window over the lyrics for every yt-dlp and every ffmpeg it ran,
which on a fetch-and-separate is several.

CREATE_NO_WINDOW says not to make that console. STARTUPINFO with SW_HIDE goes
with it because the two flags answer different halves of the question -- the
flag decides whether a console is created, the startupinfo decides how a
window the child asks for itself is shown -- and a child that opens one of
its own is not hypothetical here: ffmpeg does not, yt-dlp's ffmpeg
post-processor is another process again.

Everywhere else this is the identity function, so callers do not have to ask
what platform they are on. That is the whole point of it being here rather
than spelled out at each of the dozen call sites, which is how it was: one of
them had the flag, eleven did not.
"""
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
