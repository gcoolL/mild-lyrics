#!/usr/bin/env python3
"""Check this machine can run the lyrics app, and say what to do where it cannot.

Run it with no arguments to check the setup and put a launcher on the desktop:

    python doctor.py

Pass --no-shortcut to only check:

    python doctor.py --no-shortcut

Every check answers one question and, when the answer is no, prints the thing to
do about it. Making the launcher is the only thing here that changes anything,
and it overwrites its own file rather than piling up copies.

There is one other job in here, and it checks a source rather than a machine:

    python doctor.py --source qq
    python doctor.py --source netease --song Rise --artist Skillet --length 261

That asks one lyric source for one song and prints how far it got. "The
lyrics do not appear" is not a report anybody can act on -- the walk is ten
providers wide, runs on a worker thread and swallows every failure by design,
so a source that is reachable, finds the song and then hands back nothing
looks from the window exactly like one that is blocked.
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
# The launchers -- both .desktop files and both .pyw stubs -- live one level
# up, beside the editor package. This was looking for them in aligner/, said
# "mild-lyrics.desktop is missing", and installed nothing; which is why
# neither program was ever in the applications menu.
ROOT = HERE.parent
sys.path[:0] = [str(p) for p in (ROOT, HERE) if str(p) not in sys.path]

import noconsole  # noqa: E402

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
        got = noconsole.run([exe, "config", "spotify_launch_flags"],
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
    check_other_players()


def check_other_players() -> None:
    """Who else is on the bus, and whether the window could follow them.

    For the any-media-player setting. What that needs from a player is a
    position that MOVES: MPRIS makes the property required, a player with
    nothing to put there publishes a zero that never changes, and that is the
    one failure here which looks like success -- the song plays and the words
    sit at 0:00 for the whole of it. It cannot be read off one sample, so a
    player that says it is playing is asked twice, a third of a second apart.

    Nothing here is a failure. Nobody has to have a second player, and a
    player that is merely paused is not being judged.
    """
    import time

    try:
        import dbus
        bus = dbus.SessionBus()
        names = sorted(str(n) for n in bus.list_names()
                       if str(n).startswith("org.mpris.MediaPlayer2.")
                       and not str(n).endswith(".spotify"))
    except Exception:                                       # noqa: BLE001
        return
    if not names:
        say(OK, "Other players", "none on the bus",
            "Only matters with 'Any media player' on, which is off by\n"
            "default. Play something in a browser and run this again to see\n"
            "whether the window could follow it.")
        return
    for name in names:
        who = name[len("org.mpris.MediaPlayer2."):].split(".")[0]
        try:
            obj = bus.get_object(name, "/org/mpris/MediaPlayer2")
            props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            P = "org.mpris.MediaPlayer2.Player"
            status = str(props.Get(P, "PlaybackStatus"))
            title = str((props.Get(P, "Metadata") or {}).get("xesam:title", ""))
            first = float(props.Get(P, "Position")) / 1e6
        except Exception as e:                              # noqa: BLE001
            say(WARN, f"Player: {who}", f"on the bus but will not answer ({e})")
            continue
        said = f"{status.lower()}" + (f" — {title}" if title else "")
        if status != "Playing":
            say(OK, f"Player: {who}", said + "; play something to test its clock")
            continue
        time.sleep(0.35)
        try:
            again = float(props.Get(P, "Position")) / 1e6
        except Exception:                                   # noqa: BLE001
            again = first
        if abs(again - first) > 0.05:
            say(OK, f"Player: {who}", said + f"; clock moving ({first:.1f}s)")
        else:
            say(WARN, f"Player: {who}", said + f"; clock stuck at {first:.1f}s",
                "The window will not follow this one: it says it is playing\n"
                "but not where, so the words would sit at the start of the\n"
                "song for all of it. Nothing to fix here -- it is what that\n"
                "player publishes.")


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
LAUNCHERS = [("mild-lyrics", HERE / "lyrics_gui.py"),
             ("ttml-editor", ROOT / "ttml-editor.pyw")]


def make_shortcut() -> None:
    target = ROOT / "mild-lyrics.pyw"
    if WIN:
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
            got = noconsole.run(
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
    # Both of them. The editor has had a .desktop of its own all along and
    # nothing ever copied it anywhere a menu looks.
    done = []
    for stem, entry in LAUNCHERS:
        src = ROOT / f"{stem}.desktop"
        if not src.exists() or not entry.exists():
            say(BAD, "Shortcut", f"{stem}: {src.name} or {entry.name} is missing")
            continue
        run = f"{sys.executable} {entry}"
        try:
            apps.mkdir(parents=True, exist_ok=True)
            out = apps / f"{stem}.desktop"
            lines = []
            for ln in src.read_text(encoding="utf-8").splitlines():
                # A shebang in a .desktop is decoration; KDE reads the file,
                # it never execs it.
                if ln.startswith("#!"):
                    continue
                if ln.startswith("Exec="):
                    ln = f"Exec={run}"
                elif ln.startswith("Path="):
                    ln = f"Path={ROOT}"
                lines.append(ln)
            out.write_text("\n".join(lines) + "\n", encoding="utf-8")
            out.chmod(0o755)
            done.append(str(out))
        except Exception as e:
            say(BAD, "Shortcut", f"could not write {stem}.desktop ({e})")
    if not done:
        return
    # KDE reads its menu from a cache; a file appearing underneath it is not
    # noticed until something says so.
    for cmd in (["update-desktop-database", str(apps)], ["kbuildsycoca6"],
                ["kbuildsycoca5"]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except Exception:
            pass
    say(OK, "Shortcut", "\n".join(done))


# A song every catalogue in the running order carries, word-timed, so a
# source answering nothing for it is the source and not the song.
PROBE = ("Clocks", "Coldplay", 307.0)


def trace_source(name: str, title: str, artist: str, length: float) -> None:
    """Ask one source for one song and say how far it got.

    Here because "the lyrics do not appear" is not a report anybody can act
    on -- the walk runs ten providers wide on a worker thread and swallows
    every failure by design, so a source that is reachable, finds the song
    and then hands back nothing looks exactly like one that is blocked. This
    puts each step of the walk on the screen in turn.

    QQ Music gets its stages named because its path is the longest of them:
    a search, then a download, then a triple-DES its own client implements
    wrongly and a deflate, then the furniture -- a title card and the
    speaker labels -- taken off. Any of those can be the one that fails and
    they fail differently.
    """
    sys.path.insert(0, str(HERE))
    import lyric_sources as LS

    print(f"asking {name} for {title!r} by {artist!r}\n")
    if name != "qq":
        fn = dict(LS.PROVIDERS).get(name)
        if fn is None:
            say(BAD, "Source", f"no provider called {name!r}",
                "The names are: " + ", ".join(n for n, _ in LS.PROVIDERS))
            return
        doc = fn("probe", {"title": title, "artist": artist, "length": length})
        if not doc:
            say(BAD, name, "no document")
            return
        say(OK, name, f"{LS.quality(doc)}, "
                      f"{len(LS._items(LS.SL.payload(doc)))} lines")
        return

    hits = LS._qq_hits(title, artist, length)
    if not hits:
        say(BAD, "QQ search", "nothing believable came back",
            "Either the endpoint refused the request -- which on Windows is\n"
            "usually a proxy or a TLS interception in front of it -- or it\n"
            "answered and no row matched on title, byline and length at once.")
        return
    say(OK, "QQ search", f"{len(hits)} candidate(s): "
                         + ", ".join(f"{sid} {name!r}" for sid, name, _ in hits[:3]))
    for sid, name_of, singer in hits[:LS.QQ_TRIES]:
        raw = LS._get(f"{LS.QQ_DOWN}?version=15&miniversion=82&lrctype=4"
                      f"&musicid={sid}", "text/xml")
        if not raw:
            say(BAD, f"QQ download {sid}", "no bytes")
            continue
        say(OK, f"QQ download {sid}", f"{len(raw)} bytes")
        parts = LS._qrc_parts(raw)
        if not parts.get("content"):
            say(BAD, f"QQ decrypt {sid}", "the payload did not come out as text",
                "The DES here is QQ's own broken one, ported bug for bug. If\n"
                "this is the step that fails the document arrived encrypted\n"
                "and something about it is not the shape this reads.")
            continue
        items, _wrote = LS._qrc_items(parts["content"])
        say(OK if items else BAD, f"QQ parse {sid}", f"{len(items)} timed lines")
        if not items:
            continue
        doc = LS._qq_doc(parts, name_of or title, singer or artist)
        if not doc:
            say(BAD, f"QQ document {sid}",
                "every line was dropped as furniture or as an instrumental card")
            continue
        say(OK, f"QQ document {sid}",
            f"{LS.quality(doc)}, {len(doc.get('Content') or [])} lines")
        return
    say(BAD, "QQ Music", "no candidate produced a document")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-shortcut", action="store_true",
                    help="check only; do not touch the desktop launcher")
    ap.add_argument("--source", metavar="NAME",
                    help="ask one lyric source for one song and print how far "
                         "it got, instead of checking the setup. Use it when a "
                         "source shows nothing and you cannot tell whether it "
                         "is the fetch or the drawing")
    ap.add_argument("--song", metavar="TITLE", default=PROBE[0],
                    help=f"what to ask --source for (default {PROBE[0]!r})")
    ap.add_argument("--artist", metavar="NAME", default=PROBE[1],
                    help=f"who it is by (default {PROBE[1]!r})")
    ap.add_argument("--length", type=float, metavar="SECONDS", default=PROBE[2],
                    help="how long the recording is, which is one of the three "
                         "signals a hit is believed on (default %.0f)" % PROBE[2])
    args = ap.parse_args()

    if args.source:
        trace_source(args.source, args.song, args.artist, args.length)
        return 1 if _fails else 0

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
          f"{ROOT / 'mild-lyrics.pyw' if WIN else HERE / 'lyrics_gui.py'}")
    print(f"    {'pythonw' if WIN else 'python3'} "
          f"{ROOT / 'ttml-editor.pyw'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
