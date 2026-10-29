"""Finding, installing and announcing new releases from GitHub: a zip install
gets the release's files written over it, a clean git checkout
fast-forwards. No Qt."""
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
    """"v1.0.4" -> (1, 0, 4). Anything unreadable sorts as oldest.

    A leading zero is a step of its own: "1.1.01" -> (1, 1, 0, 1), between
    1.1.0 and 1.1.1, so a small fix can come out before the next update
    without taking its number."""
    out = []
    for x in re.findall(r"\d+", str(tag or ""))[:4]:
        while len(x) > 1 and x[0] == "0":
            out.append(0)
            x = x[1:]
        out.append(int(x))
    return tuple(out) or (0,)


def newer(tag: str, than: str) -> bool:
    return parse(tag) > parse(than)


def _open(req, timeout: float):
    """urlopen, with certifi's certificates where the system's are missing
    (python.org Python on macOS)."""
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
            ok, why = _install_git(rel, say)
        else:
            ok, why = _install_zip(rel, say)
        if not ok:
            return ok, why
        if not ensure_dependencies(say):
            return False, f"{why}; dependency installation failed"
        return True, why
    except Exception as exc:                             # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def ensure_dependencies(say=lambda _m: None) -> bool:
    """Install packages added by a release before the app is restarted.

    The setup script already knows how to probe every feature and only asks
    pip for packages that are missing. Running it after each code update keeps
    an older installation from breaking when a later release starts using a
    new dependency.
    """
    setup = ROOT / "mild-setup.py"
    if not setup.is_file():
        return True                         # compatibility with old bundles
    python = pathlib.Path(sys.executable)
    if os.name == "nt" and python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    say("checking dependencies…")
    try:
        got = subprocess.run(
            [str(python), str(setup), "--venv", "--yes", "--for", "lyrics",
             "--no-doctor"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=1800,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                           if os.name == "nt" else 0),
            check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return got.returncode == 0


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
            root = ROOT.resolve()
            for n in wanted:
                rel_path = pathlib.PurePosixPath(n[len(top):])
                # "D:x" is not absolute to PurePosixPath, yet on Windows it
                # joins onto another drive: no drive names, and nothing that
                # resolves outside ROOT.
                if (rel_path.is_absolute() or ".." in rel_path.parts
                        or "\\" in n or ":" in n):
                    continue
                dest = ROOT.joinpath(*rel_path.parts)
                if not dest.resolve().is_relative_to(root):
                    continue
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
