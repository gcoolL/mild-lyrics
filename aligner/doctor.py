#!/usr/bin/env python3
"""Check this machine can run the lyrics app, and say what to do where it cannot.

Run it with no arguments to check the setup and put a launcher on the desktop:

    python doctor.py

Pass --no-shortcut to only check:

    python doctor.py --no-shortcut

Every check answers one question and, when the answer is no, prints the thing to
do about it. Making the launcher is the only thing here that changes anything,
and it overwrites its own file rather than piling up copies.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
WIN = os.name == "nt"
PORT = 9222

OK, WARN, BAD = "  OK  ", " ---- ", " !!!! "
_fails: list[str] = []


def say(state: str, what: str, detail: str = "", fix: str = "") -> None:
    print(f"[{state}] {what}" + (f"  {detail}" if detail else ""))
    if fix:
        for line in fix.strip().splitlines():
            print(f"         {line}")
    if state is BAD:
        _fails.append(what)


# -- the checks -------------------------------------------------------------
def check_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        say(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    else:
        say(BAD, "Python", f"{v.major}.{v.minor}", "This needs 3.10 or newer.")


def check_qt() -> None:
    try:
        from PyQt6.QtCore import QT_VERSION_STR
        import PyQt6.QtGui as G
    except ImportError:
        say(BAD, "PyQt6", "not installed", "pip install PyQt6")
        return
    say(OK, "PyQt6", f"Qt {QT_VERSION_STR}")
    # Variable-font weights need this; without it a font like Roboto can only
    # be drawn regular or bold, whatever weight is asked for.
    if hasattr(G.QFont, "setVariableAxis"):
        say(OK, "Font weights", "variable axis supported")
    else:
        say(WARN, "Font weights", f"Qt {QT_VERSION_STR} has no variable axis",
            "Custom font weights will be approximate. Qt 6.7+ fixes it:\n"
            "    pip install --upgrade PyQt6")


def check_files() -> None:
    missing = [n for n in ("lyrics_gui.py", "lyric_sources.py", "spicy_lyrics.py",
                           "genius_roman.py", "spotify_dom.py", "caches.py")
               if not (HERE / n).exists() and not (HERE.parent / n).exists()]
    if missing:
        say(BAD, "Program files", f"missing {', '.join(missing)}",
            f"Copy them next to {HERE / 'lyrics_gui.py'}")
    else:
        say(OK, "Program files", "all present")
    # The editor is a second program in the same tree and ships with it. It
    # is not required -- the player runs perfectly well alone -- so a copy
    # without it is worth saying out loud rather than failing over.
    editor = HERE.parent / "editor"
    gone = [n for n in ("app.py", "model.py", "ops.py", "player.py")
            if not (editor / n).exists()]
    if not editor.is_dir():
        say(WARN, "TTML synchroniser", "not in this copy",
            "Only the player is here. The editor is the editor/ folder next\n"
            "to this one.")
    elif gone:
        say(BAD, "TTML synchroniser", f"missing {', '.join(gone)}",
            f"The editor is incomplete. Expected them in {editor}")
    else:
        say(OK, "TTML synchroniser", "all present")


def check_spotify() -> None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=4) as r:
            targets = json.load(r)
        pages = [t for t in targets if t.get("type") == "page"]
        say(OK, "Spotify debug port", f"{len(pages)} page target(s) on {PORT}")
        return
    except Exception as e:
        pass
    fix = (
        "Spotify is not listening. It has to be started BY Spicetify for the\n"
        "launch flag to apply -- starting it from the taskbar or Start menu\n"
        "does not. The durable fix is to point your Spotify shortcut at:\n"
        "    spicetify auto\n"
        "Then set the flag once (edit the file if the CLI mangles it -- run\n"
        "`spicetify -c` to find it):\n"
        "    spotify_launch_flags   = --remote-debugging-port=9222"
    ) if WIN else (
        "Spotify is not listening. Restart it with the debug port:\n"
        "    pkill -x spotify\n"
        f"    spotify --remote-debugging-port={PORT} >/dev/null 2>&1 &"
    )
    say(BAD, "Spotify debug port", f"nothing on 127.0.0.1:{PORT}", fix)


def check_spicetify() -> None:
    exe = shutil.which("spicetify")
    if not exe:
        say(WARN, "Spicetify", "not on PATH",
            "Only needed for Spicy Lyrics as a source; the other providers\n"
            "work without it.")
        return
    try:
        got = subprocess.run([exe, "config", "spotify_launch_flags"],
                             capture_output=True, text=True, timeout=20)
        flags = (got.stdout or "").strip()
    except Exception:
        flags = ""
    if "remote-debugging-port" in flags:
        say(OK, "Spicetify launch flags", flags)
    else:
        say(WARN, "Spicetify launch flags", flags or "(empty)",
            "Set it in the config file rather than the CLI -- PowerShell\n"
            "mangles values starting with a dash. `spicetify -c` prints the\n"
            "path; the line goes under [Setting]:\n"
            "    spotify_launch_flags   = --remote-debugging-port=9222")


def check_player() -> None:
    if WIN:
        try:
            import winsdk.windows.media.control  # noqa: F401
            say(OK, "Windows media transport", "available as a backup")
        except ImportError:
            say(WARN, "Windows media transport", "winsdk not installed",
                "Optional. It lets the app keep working while the debug port\n"
                "is down, without Spicy Lyrics:\n"
                "    pip install winsdk")
        return
    try:
        import dbus
        dbus.SessionBus().get_object("org.mpris.MediaPlayer2.spotify",
                                     "/org/mpris/MediaPlayer2")
        say(OK, "MPRIS", "Spotify is on the session bus")
    except Exception:
        say(WARN, "MPRIS", "Spotify not on the session bus",
            "The app will drive the clock over the debug port instead.")


def check_extras() -> None:
    if shutil.which("ffmpeg"):
        say(OK, "ffmpeg", "animated covers available")
    else:
        say(WARN, "ffmpeg", "not on PATH",
            "Only needed for animated album covers, which are off by default.")
    try:
        import pykakasi  # noqa: F401
        say(OK, "pykakasi", "Japanese romanisation available")
    except ImportError:
        say(WARN, "pykakasi", "not installed",
            "Only needed to derive romanisation for Japanese lyrics:\n"
            "    pip install pykakasi")


def check_caches() -> None:
    """What the app has left on the disk, and what it would take to get back.

    A warning at worst, and usually not even that -- a large cache is the
    app working, not the app broken. It is here because it is the one thing
    on this list nobody discovers on their own: art and animated covers
    accumulate one song at a time, and the first anybody knows of it is a
    full disk.
    """
    try:
        import caches
    except Exception as exc:                             # noqa: BLE001
        say(WARN, "Caches", f"could not read them ({exc})")
        return
    rows = caches.survey()
    total = sum(r["bytes"] for r in rows)
    big = [r for r in rows if r["bytes"] > 0][:4]
    detail = ", ".join(f"{r['key']} {r['human']}" for r in big) or "nothing yet"
    state = WARN if total > 2 * 1024 ** 3 else OK
    say(state, "Caches", f"{caches.human(total)} in {caches.cache_dir()}",
        f"Largest: {detail}\n"
        "Everything in there is derived and safe to clear:\n"
        f"    {sys.executable} {HERE / 'caches.py'}\n"
        f"    {sys.executable} {HERE / 'caches.py'} --clear all\n"
        "The ones marked * are work this machine did -- alignments and the\n"
        "editor's backups -- and are kept unless --everything is added."
        if state is WARN else f"Largest: {detail}")


def check_token() -> None:
    """Credentials this copy is holding, and how to be rid of them.

    Two of them, and they are not the same kind of thing. The Genius token
    is typed in by a person and is theirs; the Apple one is lifted from the
    web player's own bundle and belongs to nobody. Both are worth naming
    before a copy of this goes to somebody else.
    """
    try:
        import caches
        held = caches.credentials()
    except Exception:
        return
    have = [c for c in held if c["present"]]
    if not have:
        say(OK, "Credentials", "none stored")
        return
    say(WARN, "Credentials", ", ".join(c["label"] for c in have),
        "Stored on this machine, not in the program files. Clear them\n"
        "before handing this copy to somebody else:\n"
        f"    {sys.executable} {HERE / 'caches.py'} --forget")


def check_align() -> None:
    """The local forced aligner: what it needs, and what the card has spare.

    Every line here is a warning at worst. Nothing in the window uses any of
    it -- align_song.py does, on demand, one song at a time -- so a machine
    without a GPU or without torch is not a broken install, it is simply one
    that will not be timing anything against its own audio.
    """
    missing = [m for m in ("torch", "torchaudio", "soundfile", "demucs")
               if not _has(m)]
    if missing:
        extra = ("\nThe demucs command on PATH is not enough: this imports the\n"
                 "library, and pipx-style installs hide it inside their own venv."
                 if "demucs" in missing and shutil.which("demucs") else "")
        say(WARN, "Local alignment", f"missing {', '.join(missing)}",
            "Only needed for align_song.py, which times a song against its own\n"
            "audio rather than trusting somebody else's stamps. It is a large\n"
            "download (torch is over a gigabyte):\n"
            f"    {sys.executable} -m pip install --user "
            f"{' '.join(missing)}{extra}")
        return
    say(OK, "Local alignment", "torch, torchaudio, soundfile and demucs")
    sys.path.insert(0, str(HERE))
    try:
        import local_align as LA
        got = LA.survey()
    except Exception as exc:
        say(WARN, "Alignment GPU", f"could not ask the card ({exc})")
        return
    if got is None:
        say(WARN, "Alignment GPU", "no usable CUDA device",
            "Both stages will run on the CPU. That works and is several times\n"
            "slower -- minutes per song rather than tens of seconds.")
        return
    free = f"{got['free']:.1f} of {got['total']:.1f} GB free"
    # Asked of the planner rather than guessed at, so this says what would
    # actually happen if the tool were run at this moment -- which depends on
    # what else is on the card right now, not on what the card is.
    plan = [f"{what} on {LA.room('auto', cost, win)[0]}"
            for what, cost, win in (("separation", LA.DEMUCS_COST, LA.DEMUCS_WINDOW),
                                    ("alignment", LA.ALIGN_COST, LA.ALIGN_WINDOW))]
    on_gpu = all("cuda" in p for p in plan)
    say(OK if on_gpu else WARN, "Alignment GPU", f"{got['name']}, {free}",
        "" if on_gpu else
        f"Right now that means {', '.join(plan)}.\n"
        "Close whatever else is holding the card, or accept the CPU.")
    check_syllables()


def check_syllables() -> None:
    """Whether an English alignment can be divided into syllables.

    Optional at every step, and never a failure. Without any of it a word is
    timed as a word, which is what the aligner did before this existed --
    and no other language goes near it, since espeak's phonemes are per
    language while the aligner's romanised alphabet is not.
    """
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    missing = [m for m in ("phonemizer", "transformers") if not _has(m)]
    if not espeak:
        missing.append("espeak-ng (the program, not a pip package)")
    if not missing:
        say(OK, "Syllables", "English words divided by their pronunciation")
        return
    say(WARN, "Syllables", f"missing {', '.join(missing)}",
        "English words will be timed whole rather than divided into\n"
        "syllables. Everything else is unaffected, and no other language\n"
        "uses this at all:\n"
        f"    {sys.executable} -m pip install --user phonemizer transformers\n"
        "    (and espeak-ng from your package manager)\n"
        "transformers alone is the sharper boundary; phonemizer alone still\n"
        "divides the words in the right places.")


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


# -- the shortcut -----------------------------------------------------------
def make_shortcut() -> None:
    target = HERE / "mild-lyrics.pyw"
    if WIN:
        # Built by a temp .ps1 rather than -Command: the paths carry spaces and
        # the nested quoting needed to survive one line of PowerShell is where
        # this failed before. The Desktop path is asked of Windows rather than
        # assumed, because OneDrive moves it and %USERPROFILE%\Desktop is then
        # a folder that does not exist.
        pyw = pathlib.Path(sys.executable).with_name("pythonw.exe")
        exe = pyw if pyw.exists() else pathlib.Path(sys.executable)
        script = (
            "$ErrorActionPreference = 'Stop'\n"
            "$desk = [Environment]::GetFolderPath('Desktop')\n"
            "if (-not (Test-Path $desk)) { $desk = $env:USERPROFILE }\n"
            "$link = Join-Path $desk 'Mild Lyrics.lnk'\n"
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($link)\n"
            f"$s.TargetPath = '{exe}'\n"
            f'$s.Arguments = \'"{target}"\'\n'
            f"$s.WorkingDirectory = '{HERE}'\n"
            "$s.Save()\n"
            "Write-Output $link\n"
        )
        tmp = pathlib.Path(tempfile.gettempdir()) / "mild-lyrics-shortcut.ps1"
        try:
            tmp.write_text(script, encoding="utf-8")
            got = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
                capture_output=True, text=True, timeout=40)
            if got.returncode == 0 and got.stdout.strip():
                say(OK, "Shortcut", got.stdout.strip())
            else:
                why = (got.stderr or got.stdout or "no output").strip().splitlines()
                say(BAD, "Shortcut", "PowerShell refused",
                    "\n".join(why[:3]) + "\n"
                    "Make one by hand instead: right-click the desktop,\n"
                    "New > Shortcut, and enter\n"
                    f'    "{exe}" "{target}"')
        except FileNotFoundError:
            say(BAD, "Shortcut", "powershell not found",
                f'Make one by hand pointing at:\n    "{exe}" "{target}"')
        except Exception as e:
            say(BAD, "Shortcut", f"{type(e).__name__}: {e}",
                f'Make one by hand pointing at:\n    "{exe}" "{target}"')
        finally:
            tmp.unlink(missing_ok=True)
        return
    apps = pathlib.Path.home() / ".local" / "share" / "applications"
    src = HERE / "mild-lyrics.desktop"
    if not src.exists():
        say(BAD, "Shortcut", "mild-lyrics.desktop is missing")
        return
    try:
        apps.mkdir(parents=True, exist_ok=True)
        text = "\n".join(
            f"Exec={sys.executable} {HERE / 'lyrics_gui.py'}"
            if ln.startswith("Exec=") else ln
            for ln in src.read_text(encoding="utf-8").splitlines()) + "\n"
        out = apps / "mild-lyrics.desktop"
        out.write_text(text, encoding="utf-8")
        say(OK, "Shortcut", str(out))
    except Exception as e:
        say(BAD, "Shortcut", f"could not write ({e})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-shortcut", action="store_true",
                    help="check only; do not touch the desktop launcher")
    args = ap.parse_args()

    print(f"Mild Lyrics setup check  --  {'Windows' if WIN else os.uname().sysname}")
    print(f"{HERE}\n")
    check_python()
    check_qt()
    check_files()
    check_spotify()
    check_spicetify()
    check_player()
    check_extras()
    check_align()
    check_caches()
    check_token()
    if not args.no_shortcut:
        print()
        make_shortcut()

    print()
    if _fails:
        print(f"{len(_fails)} thing(s) need attention: {', '.join(_fails)}")
        return 1
    print("Ready. Use the desktop shortcut, or:")
    print(f"    {'pythonw' if WIN else 'python3'} "
          f"{HERE / ('mild-lyrics.pyw' if WIN else 'lyrics_gui.py')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
