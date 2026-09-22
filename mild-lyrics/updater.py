"""Finding, installing and announcing new releases of Mild Lyrics.

Everything comes from GitHub, which is the only place a release exists: the
latest release says which version is current, its notes are the changelog,
and its tag names the source to install. No login is needed for any of it --
the public API allows sixty unauthenticated requests an hour, and this makes
one on startup.

Two kinds of install, updated two different ways:

  - a copy downloaded as a zip. The release's own source archive is fetched
    and its files are written over the program's. Only files that are IN the
    release are touched; the settings, caches and lyrics live elsewhere or
    are not part of a release, so they are left exactly as they were.

  - a git checkout. It is moved to the release tag with a fast-forward, and
    only when that is safe: nothing uncommitted, and nothing committed that
    the release does not already contain. A checkout somebody is working in
    is never touched -- the caller is told an update exists instead.

Qt is deliberately not imported here, so this can be driven and tested
without a window.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = "gcoolL/mild-lyrics"
# Overridable so the whole path -- check, download, install -- can be run
# against a local stand-in for GitHub. See the 1.0.4 release notes.
API = os.environ.get("MILD_UPDATE_API", "https://api.github.com").rstrip("/")
TIMEOUT = 15.0
UA = "mild-lyrics-updater"


def parse(tag: str) -> tuple:
    """"v1.0.4" -> (1, 0, 4). Anything unreadable sorts as oldest."""
    got = re.findall(r"\d+", str(tag or ""))
    return tuple(int(x) for x in got[:4]) or (0,)


def newer(tag: str, than: str) -> bool:
    return parse(tag) > parse(than)


def _open(req, timeout: float):
    """urlopen, with certifi's certificates where the system's are missing.

    Python from python.org on macOS ships without a certificate store until
    its "Install Certificates" script has been run, and every HTTPS request
    then fails verification. certifi, where it is installed, is the same
    bundle that script would have put there.
    """
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        try:
            import certifi
        except ImportError:
            raise exc from None
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def _get(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/vnd.github+json"})
    with _open(req, TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def latest() -> dict | None:
    """The newest published release, as {tag, name, notes, zip}, or None."""
    got = _get(f"{API}/repos/{REPO}/releases/latest")
    if not isinstance(got, dict) or not got.get("tag_name"):
        return None
    return {"tag": got["tag_name"], "name": got.get("name") or got["tag_name"],
            "notes": got.get("body") or "",
            "zip": got.get("zipball_url")
            or f"{API}/repos/{REPO}/zipball/{got['tag_name']}"}


def changes_between(old: str, new: str) -> list[dict]:
    """Every release after `old` up to and including `new`, newest first."""
    got = _get(f"{API}/repos/{REPO}/releases?per_page=30")
    out = []
    for rel in got if isinstance(got, list) else []:
        tag = rel.get("tag_name") or ""
        if rel.get("draft") or not tag:
            continue
        if newer(tag, old) and not newer(tag, new):
            out.append({"tag": tag, "name": rel.get("name") or tag,
                        "notes": rel.get("body") or ""})
    out.sort(key=lambda r: parse(r["tag"]), reverse=True)
    return out


# ------------------------------------------------------------------ install
def _git(*args, check: bool = True) -> subprocess.CompletedProcess:
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, timeout=120, check=check, **kw)


def is_checkout() -> bool:
    return (ROOT / ".git").exists()


def install(rel: dict, say=lambda _m: None) -> tuple[bool, str]:
    """Put `rel` in place. (done, what happened, in words)."""
    try:
        if is_checkout():
            return _install_git(rel, say)
        return _install_zip(rel, say)
    except Exception as exc:                             # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _install_git(rel: dict, say) -> tuple[bool, str]:
    tag = rel["tag"]
    if not shutil.which("git"):
        return False, "this is a git checkout and git is not on PATH"
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return False, ("this checkout has uncommitted changes -- update it "
                       "yourself with git")
    say(f"fetching {tag}…")
    url = os.environ.get("MILD_UPDATE_GIT") or f"https://github.com/{REPO}.git"
    _git("fetch", "--quiet", "--no-tags", url,
         f"refs/tags/{tag}:refs/tags/{tag}")
    if _git("merge-base", "--is-ancestor", "HEAD", tag,
            check=False).returncode != 0:
        return False, ("this checkout has commits the release does not -- "
                       "update it yourself with git")
    if _git("symbolic-ref", "-q", "HEAD", check=False).returncode == 0:
        _git("merge", "--quiet", "--ff-only", tag)
    else:
        _git("checkout", "--quiet", tag)
    return True, f"moved the checkout to {tag}"


def _install_zip(rel: dict, say) -> tuple[bool, str]:
    say(f"downloading {rel['tag']}…")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mild-update-"))
    try:
        blob = tmp / "release.zip"
        req = urllib.request.Request(rel["zip"], headers={"User-Agent": UA})
        with _open(req, 120) as r, open(blob, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(blob) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            if not names:
                return False, "the release archive was empty"
            # GitHub puts everything under one "<owner>-<repo>-<sha>/" folder.
            top = names[0].split("/", 1)[0] + "/"
            if not all(n.startswith(top) for n in names):
                top = ""
            wanted = [n for n in names if n[len(top):]]
            if not any(n[len(top):] == "mild-lyrics/lyrics_gui.py"
                       for n in wanted):
                return False, "that archive is not a Mild Lyrics release"
            say("installing…")
            for n in wanted:
                rel_path = pathlib.PurePosixPath(n[len(top):])
                if rel_path.is_absolute() or ".." in rel_path.parts:
                    continue
                dest = ROOT.joinpath(*rel_path.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                part = dest.with_name(dest.name + ".part")
                with z.open(n) as src, open(part, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.replace(part, dest)
        return True, f"installed {rel['tag']}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ restart
def restart(argv: list[str] | None = None) -> None:
    """Start Mild Lyrics again once this process has gone.

    A helper process waits for this one to exit -- the window holds a local
    port the new one needs -- and then starts the same interpreter with the
    same arguments. The caller quits right after calling this.
    """
    argv = list(argv if argv is not None else sys.argv)
    if argv and argv[0] and os.path.exists(argv[0]):
        argv[0] = os.path.abspath(argv[0])
    exe = sys.executable
    if os.name == "nt":
        pyw = pathlib.Path(exe).with_name("pythonw.exe")
        if pyw.exists():
            exe = str(pyw)
    helper = (
        "import os, subprocess, sys, time\n"
        "pid = int(sys.argv[1])\n"
        "def alive(p):\n"
        "    if os.name == 'nt':\n"
        "        import ctypes\n"
        "        h = ctypes.windll.kernel32.OpenProcess(0x100000, 0, p)\n"
        "        if not h: return False\n"
        "        r = ctypes.windll.kernel32.WaitForSingleObject(h, 0)\n"
        "        ctypes.windll.kernel32.CloseHandle(h)\n"
        "        return r == 0x102\n"
        "    try: os.kill(p, 0)\n"
        "    except OSError: return False\n"
        "    return True\n"
        "t = time.time()\n"
        "while alive(pid) and time.time() - t < 30: time.sleep(0.2)\n"
        "subprocess.Popen(sys.argv[2:])\n"
    )
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                               | getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        kw["start_new_session"] = True
    subprocess.Popen([exe, "-c", helper, str(os.getpid()), exe, *argv], **kw)


def wait_for(check, seconds: float) -> bool:
    """Poll `check` until it is true or time runs out. For the tests."""
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.2)
    return False
