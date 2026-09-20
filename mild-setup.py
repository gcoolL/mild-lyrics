#!/usr/bin/env python3
"""Check this machine can run Mild Lyrics, and offer to install what it cannot.

Run it with no arguments:

    python3 mild-setup.py            (Linux, macOS)
    py -3 mild-setup.py              (Windows)

or use the wrapper for the platform, which finds a Python first and says
where to get one when there is none:

    ./setup.sh                       (Linux, macOS)
    setup.cmd                        (Windows -- double-click works too)

What is on the list is what the player and the editor import -- the two
programs in mild-lyrics/ and editor/ -- and the handful of outside programs they
shell out to. Nothing else in the tree is checked here.

Three questions, in this order, and nothing is installed without being asked:

  1. Is the Python here new enough, and does it have pip.
  2. Which packages are missing, per feature, so a missing one can be read
     as "no waveform" rather than as a name.
  3. Do the ones that ARE here actually work -- which is a different
     question, and the reason this exists next to a list of pip names.

That third question is the point of the whole file. An import is not a
working install: torch on a CPU older than its wheels kills the interpreter
outright with an illegal instruction, a PyQt6 with no platform plugin
imports and then cannot open a window, and soundfile without libsndfile
imports and fails on the first file. So every check here runs in a CHILD
interpreter, one line of output per package, flushed. A child that dies
takes nothing with it, and the package it died on is the one after the last
line it managed to print.

The heavy group -- torch, demucs and what they drag in -- is never installed
on a yes. It is several gigabytes, and it is the only thing here whose
failures are the machine's rather than the package's: too little memory, a
CPU older than the wheels, no card, a Python too new to have wheels at all.
So that group prints what this machine actually is, says what each of those
will mean here, and then wants the word "yes" typed out.

This is the front door. `mild-lyrics/doctor.py` is the room-by-room check --
players, the Spotify debug port, caches, credentials, and the desktop
shortcuts -- and is worth running after this one; the last line here offers.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import sysconfig
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent

WIN = os.name == "nt"
MAC = sys.platform == "darwin"
LINUX = not WIN and not MAC
HERE = "win" if WIN else "mac" if MAC else "linux"

MIN_PY = (3, 10)
GB = 1024 ** 3

OK, WARN, BAD = "  OK  ", " ---- ", " !!!! "
_fails: list[str] = []
_warns: list[str] = []


def wrap(text: str, first: str = "    ", rest: str = "    ") -> None:
    """A paragraph at a width a terminal will not fold for us.

    The prose here is the point -- a missing package is only useful named
    next to what it is for -- and prose the terminal wraps itself breaks
    wherever the window happens to end, which is never where a sentence
    does.
    """
    print(textwrap.fill(" ".join(text.split()), width=76,
                        initial_indent=first, subsequent_indent=rest))


def spawn(cmd: list[str]) -> int:
    """Run a child that prints for itself, after emptying our own buffer.

    Our output is block-buffered the moment this is piped into anything --
    a log file, a pager, a bug report -- while a child writes to the same
    place immediately. Without the flush, every line pip and doctor print
    lands AHEAD of the lines here that introduce them, and the report reads
    back in an order nothing actually happened in.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run(cmd).returncode


def say(state: str, what: str, detail: str = "", fix: str = "") -> None:
    """One line for one question, and the thing to do when the answer is no.

    Deliberately the same shape as doctor.py's: a machine that has both of
    these run on it should not have to be read two ways.
    """
    print(f"[{state}] {what}" + (f"  {detail}" if detail else ""))
    if fix:
        for line in fix.strip().splitlines():
            print(f"         {line}")
    if state is BAD:
        _fails.append(what)
    elif state is WARN:
        _warns.append(what)


# -- what this project needs ------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Dep:
    """One importable package, and how to tell whether it really works.

    `module` is what the code imports and `pip` is what pip is asked for;
    they differ often enough (`soundfile`, `silero-vad`, `dbus-python`) that
    keeping one field for both would be a bug waiting in the install line.

    `smoke` is an expression run in the child with the imported module bound
    to `m`. It exists for the packages whose import proves the least: a
    compiled extension that loaded is not a library that found the shared
    object it wraps.

    `instead` is a second module that answers the same question, and the row
    is satisfied by either. One thing needs it -- Windows publishes its media
    bindings under two package names, and the older one is what this
    project's own instructions used to ask for, so a machine that followed
    them has everything it needs under a name that is not in the `pip`
    field.
    """
    module: str
    pip: str
    what: str
    smoke: str = ""
    instead: str = ""


@dataclasses.dataclass(frozen=True)
class Group:
    """A feature, and the packages without which it is simply not there.

    Grouped by what is lost rather than by size, because that is the only
    form in which the question "do I want this" can be answered by somebody
    who has not read the source. `need` is what a missing one means:

        required  the window and the editor will not start
        wanted    a visible feature goes missing, and the cost is small
        optional  a nicety; most machines are fine without it
        heavy     gigabytes, and the group that can make a machine worse
    """
    key: str
    title: str
    why: str
    need: str
    deps: tuple[Dep, ...]
    only: str = ""
    warn: str = ""


GROUPS: tuple[Group, ...] = (
    Group(
        "core", "The window and the editor",
        "Both programs are Qt. Without this there is nothing to start.",
        "required",
        (Dep("PyQt6.QtWidgets", "PyQt6", "the whole user interface",
             "'Qt ' + __import__('PyQt6.QtCore', fromlist=['x'])"
             ".QT_VERSION_STR"),),
    ),
    Group(
        "audio", "Waveform and vocal map",
        "The editor draws a song's loudness under the lines, and reads a "
        "separated vocal to place syllables. Both read the audio in-process.",
        "wanted",
        (Dep("numpy", "numpy", "the arithmetic under both",
             "'arithmetic ok' if m.zeros(4).sum() == 0 else 'wrong answers'"),
         Dep("soundfile", "soundfile", "reads wav and flac",
             "'libsndfile ' + m.__libsndfile_version__")),
    ),
    Group(
        "words", "Syllables and romanisation",
        "Splitting a word where it is pronounced, and writing a line that is "
        "not in the Latin alphabet in one that is.",
        "optional",
        (Dep("pyphen", "pyphen", "hyphenation, in the editor's syllable split",
             "'%d languages' % len(m.LANGUAGES)"),
         Dep("pykakasi", "pykakasi", "Japanese kana to romaji"),
         Dep("pypinyin", "pypinyin", "Chinese to pinyin"),
         Dep("uroman", "uroman", "everything else to the Latin alphabet")),
    ),
    Group(
        "mpris", "Reading the player",
        "Which song is playing and where it is up to, over the session bus. "
        "Without it the window can only follow Spotify, over the debug port.",
        "optional", (Dep("dbus", "dbus-python", "the session bus"),),
        only="linux",
    ),
    Group(
        "winmedia", "Reading the player",
        "The Windows media transport: which song is playing, in any player "
        "including the browsers, and the name of the output device. There "
        "are two packages with one API: winrt is the maintained one and has "
        "wheels through 3.14, while winsdk's last is for 3.12 -- and where "
        "winsdk is already installed and answering, that is this row "
        "satisfied and nothing needs installing.",
        "optional",
        (Dep("winrt.windows.media.control", "winrt-Windows.Media.Control",
             "what is playing",
             instead="winsdk.windows.media.control"),
         Dep("winrt.windows.media.devices", "winrt-Windows.Media.Devices",
             "which output it is playing to",
             instead="winsdk.windows.media.devices"),
         Dep("winrt.windows.devices.enumeration",
             "winrt-Windows.Devices.Enumeration", "that output's name",
             instead="winsdk.windows.devices.enumeration"),
         Dep("winrt.windows.storage.streams", "winrt-Windows.Storage.Streams",
             "the cover art bytes",
             instead="winsdk.windows.storage.streams")),
        only="win",
    ),
    Group(
        "align", "Local alignment",
        "Timing a song against its own audio rather than trusting somebody "
        "else's stamps: demucs takes the vocal out of the mix, and a CTC "
        "model puts every word where it is sung.",
        "heavy",
        (Dep("torch", "torch", "the runtime everything below sits on",
             "('CUDA: ' + m.cuda.get_device_name(0)) if "
             "(m.zeros(8).sum().item() == 0 and m.cuda.is_available()) "
             "else 'imports and computes; no CUDA device, so the CPU'"),
         Dep("torchaudio", "torchaudio", "reading and resampling the audio"),
         Dep("demucs", "demucs", "separating the vocal from the mix",
             "__import__('demucs.pretrained') and "
             "'weights (~300 MB) download on the first real run'"),
         Dep("transformers", "transformers", "the acoustic model"),
         Dep("silero_vad", "silero-vad", "where in the stem there are words")),
    ),
    Group(
        "phonemes", "English syllables by pronunciation",
        "Dividing an English word the way it is said rather than the way it "
        "is spelled. It also needs the espeak-ng PROGRAM, checked below.",
        "optional",
        (Dep("phonemizer", "phonemizer", "words to phonemes, through espeak",
             "'espeak backend available' if __import__("
             "'phonemizer.backend', fromlist=['x']).EspeakBackend.is_available()"
             " else 'installed, but it cannot find espeak-ng'"),),
    ),
)


def wanted(g: Group) -> bool:
    return not g.only or g.only == HERE


# -- asking the child ------------------------------------------------------


_PROBE = r'''
import importlib, json, sys

def version(mod, dist):
    v = getattr(mod, "__version__", "")
    if not v:
        try:
            from importlib.metadata import version as _v
            v = _v(dist)
        except Exception:
            v = ""
    return str(v)

for spec in json.loads(sys.stdin.read()):
    row = {"module": spec["module"]}
    try:
        mod = importlib.import_module(spec["module"])
        row["ok"] = True
        row["version"] = version(mod, spec["pip"])
        if spec["smoke"]:
            try:
                row["note"] = str(eval(spec["smoke"], {"m": mod}) or "")
            except BaseException as exc:
                row["note"] = ""
                row["broke"] = "%s: %s" % (type(exc).__name__, exc)
    except BaseException as exc:
        row["ok"] = False
        row["why"] = "%s: %s" % (type(exc).__name__, exc)
    print(json.dumps(row), flush=True)
'''


def died(code: int) -> str:
    """How a child interpreter ended, said in words rather than in a number.

    Worth the lookup: the two codes that matter here are the two that an
    install can be wrong in a way no import error will ever mention. An
    illegal instruction is a wheel built for a newer CPU than this one; an
    access violation or segmentation fault is usually a compiled extension
    meeting a shared library it was not built against.
    """
    if code < 0:
        try:
            import signal
            name = signal.Signals(-code).name
        except Exception:
            name = f"signal {-code}"
        extra = {"SIGILL": " -- illegal instruction",
                 "SIGSEGV": " -- segmentation fault",
                 "SIGKILL": " -- killed, usually by the out-of-memory killer",
                 "SIGABRT": " -- aborted"}.get(name, "")
        return f"{name}{extra}"
    known = {0xC000001D: "illegal instruction",
             0xC0000005: "access violation",
             0xC0000409: "stack buffer overrun",
             0xC0000135: "a DLL it needs is not on this machine"}
    if code in known:
        return f"0x{code:08X} -- {known[code]}"
    return f"exit code {code}"


def probe(python: pathlib.Path, deps: tuple[Dep, ...]) -> dict[str, dict]:
    """Import each of `deps` in one child, and say what happened to each.

    One child rather than one per package, because importing torch four
    times over costs more than the rest of this script put together -- and
    one child is all it takes to attribute a crash, as long as the child
    prints as it goes. The row for a package that never printed is filled in
    here from how the child died, which is the only way a wheel that is
    wrong for this CPU ever gets a name printed next to it.
    """
    spec = []
    for d in deps:
        spec.append({"module": d.module, "pip": d.pip, "smoke": d.smoke})
        if d.instead:
            spec.append({"module": d.instead, "pip": d.pip, "smoke": ""})
    try:
        got = subprocess.run([str(python), "-c", _PROBE],
                             input=json.dumps(spec), text=True,
                             capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {x["module"]: {"module": x["module"], "ok": False,
                              "why": "the import did not finish in 5 minutes"}
                for x in spec}
    rows: dict[str, dict] = {}
    for line in (got.stdout or "").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        rows[row["module"]] = row
    if got.returncode != 0:
        left = [x["module"] for x in spec if x["module"] not in rows]
        if left:
            blame, rest = left[0], tuple(
                Dep(x["module"], x["pip"], "", x["smoke"])
                for x in spec if x["module"] in left[1:])
            rows[blame] = {"module": blame, "ok": False,
                           "crash": died(got.returncode),
                           "why": "the import ended the interpreter "
                                  f"({died(got.returncode)})"}
            # Everything after it was never asked -- the child was gone. Ask
            # again without the one that killed it, rather than report a pile
            # of packages as missing on the strength of never having been
            # looked for. Each round is one package shorter, so this ends.
            if rest:
                rows.update(probe(python, rest))
    for x in spec:
        rows.setdefault(x["module"], {"module": x["module"], "ok": False,
                                      "why": "not installed"})
    return rows


def report(group: Group, rows: dict[str, dict]) -> list[Dep]:
    """Print a line per package and hand back the ones that are not working.

    A package that imported and then failed its own smoke test is returned
    with the missing ones. Reinstalling it is not certain to help, and it is
    certainly not working, so it belongs on the same list rather than in a
    footnote under a line that says OK.
    """
    state = {"required": BAD, "wanted": WARN,
             "optional": WARN, "heavy": WARN}[group.need]
    broken: list[Dep] = []
    for dep in group.deps:
        row = rows.get(dep.module, {})
        other = rows.get(dep.instead, {}) if dep.instead else {}
        if not row.get("ok") and other.get("ok"):
            say(OK, f"{group.title}: {dep.pip}",
                f"{dep.instead.split('.')[0]} "
                f"{other.get('version', '')}".strip()
                + " answers for it")
            continue
        if not row.get("ok"):
            broken.append(dep)
            why = row.get("why", "not installed")
            crash = row.get("crash")
            say(state, f"{group.title}: {dep.pip}",
                "not installed" if why == "not installed" else why,
                "" if not crash else
                "It is installed -- importing it is what killed the child\n"
                "interpreter, so nothing that imports it can run here. That is\n"
                "the wheel against this machine, not a missing package:\n"
                "reinstalling the same one will do the same thing.")
            continue
        seen = " ".join(x for x in (row.get("version", ""),
                                    row.get("note", "")) if x)
        if row.get("broke"):
            broken.append(dep)
            say(state, f"{group.title}: {dep.pip}",
                f"{row.get('version', '')} imports, and then does not work",
                row["broke"] + "\n"
                "The package is installed. Something it needs outside Python\n"
                "-- a shared library, a program on PATH -- is what is missing.")
            continue
        say(OK, f"{group.title}: {dep.pip}", seen or dep.what)
    return broken


# -- what this machine is --------------------------------------------------


def ram_gb() -> float:
    """Total memory, or 0.0 where this platform will not say.

    Asked because the heavy group is the one thing here that can leave a
    machine worse than it found it, and memory is what decides that: demucs
    holding a window of a song plus a model is where a small machine gets
    its process killed rather than merely slowed down.
    """
    try:
        if WIN:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = Status()
            st.dwLength = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / GB
        if MAC:
            got = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=10)
            return int(got.stdout.strip()) / GB
        return (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / GB
    except Exception:
        return 0.0


def cpu_flags() -> set[str]:
    """Lowercased CPU feature names, where the platform publishes them.

    Empty on Windows, which does not, and an empty set is read here as "not
    known" rather than as "not present" -- the check below only ever speaks
    up about a flag it has positively failed to find.
    """
    try:
        if LINUX:
            for line in pathlib.Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("flags") or line.startswith("Features"):
                    return set(line.split(":", 1)[1].split())
        if MAC:
            got = subprocess.run(["sysctl", "-n", "machdep.cpu.features",
                                  "machdep.cpu.leaf7_features"],
                                 capture_output=True, text=True, timeout=10)
            return set(got.stdout.lower().split())
    except Exception:
        pass
    return set()


def nvidia() -> str:
    """The name of the first NVIDIA card, or "" -- asked of the driver.

    nvidia-smi rather than torch, because this runs BEFORE torch is
    installed and the answer is half of what the decision is made on.
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return ""
    try:
        got = subprocess.run([exe, "--query-gpu=name,memory.total",
                              "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=20)
        first = (got.stdout or "").strip().splitlines()
        return first[0].strip() if first else ""
    except Exception:
        return ""


def machine() -> dict:
    ram = ram_gb()
    flags = cpu_flags()
    free = shutil.disk_usage(ROOT).free / GB
    arm_mac = MAC and platform.machine() == "arm64"
    return {"ram": ram, "flags": flags, "cores": os.cpu_count() or 0,
            "free": free, "gpu": nvidia(), "arm_mac": arm_mac,
            "x86": platform.machine().lower() in
                   ("x86_64", "amd64", "i386", "i686", "x86")}


def misgivings(m: dict) -> list[str]:
    """Everything about THIS machine that argues against the heavy group.

    Each line is a measurement and what it will mean, not a score. A machine
    that draws several of these can still run all of it; the point is that
    somebody should get to decide that knowing what it costs, rather than
    find out when the first song takes forty minutes.
    """
    out = []
    if m["ram"] and m["ram"] < 8:
        out.append(f"{m['ram']:.1f} GB of memory. Separating a song holds a "
                   "model and a window of audio at once; under about 8 GB "
                   "that is where the process gets killed rather than merely "
                   "slowed.")
    if m["free"] < 8:
        out.append(f"{m['free']:.1f} GB free on this disk. The download alone "
                   "is 2-3 GB on a CUDA build, and the model weights are "
                   "several hundred megabytes more.")
    if m["x86"] and m["flags"] and "avx2" not in m["flags"]:
        out.append("this CPU has no AVX2. The published wheels pick their "
                   "kernels at runtime, and the ones that have no fallback "
                   "are where an older CPU dies with an illegal instruction "
                   "rather than an error message. The check after the install "
                   "is written to catch exactly that.")
    if m["cores"] and m["cores"] < 4:
        out.append(f"{m['cores']} CPU cores. With no card, separation is the "
                   "slow half, and it is the half that scales with cores.")
    if not m["gpu"] and not m["arm_mac"]:
        out.append("no NVIDIA card was found, so both stages run on the CPU. "
                   "That works -- it is three to ten times slower, minutes "
                   "per song rather than tens of seconds.")
    if sys.version_info >= (3, 13):
        out.append(f"this is Python {platform.python_version()}. torch, "
                   "torchaudio and demucs are slow to publish wheels for a "
                   "new Python; where there is none, pip falls back to "
                   "building from source, which needs a compiler and "
                   "usually just fails. A 3.11 or 3.12 alongside this one is "
                   "the cheap way out.")
    return out


# -- where to install it ---------------------------------------------------


def managed(python: pathlib.Path) -> bool:
    """Whether this interpreter belongs to the operating system.

    PEP 668: a distribution that manages its own site-packages drops an
    EXTERNALLY-MANAGED file next to the stdlib, and pip refuses to write
    there -- including `pip install --user`, which is the line most
    instructions still give. Worth knowing BEFORE an install is offered,
    because on those machines the honest options are a virtual environment
    or the distribution's own packages, and neither is pip's default.
    """
    if str(python) == sys.executable:
        stdlib = sysconfig.get_path("stdlib")
    else:
        try:
            got = subprocess.run(
                [str(python), "-c",
                 "import sysconfig;print(sysconfig.get_path('stdlib'))"],
                capture_output=True, text=True, timeout=30)
            stdlib = got.stdout.strip()
        except Exception:
            return False
    return bool(stdlib) and (pathlib.Path(stdlib) / "EXTERNALLY-MANAGED").exists()


def in_venv(python: pathlib.Path) -> bool:
    if str(python) == sys.executable:
        return sys.prefix != sys.base_prefix
    try:
        got = subprocess.run(
            [str(python), "-c",
             "import sys;print(sys.prefix != sys.base_prefix)"],
            capture_output=True, text=True, timeout=30)
        return got.stdout.strip() == "True"
    except Exception:
        return False


def venv_python(venv: pathlib.Path) -> pathlib.Path:
    return venv / ("Scripts" if WIN else "bin") / ("python.exe" if WIN
                                                   else "python3")


def make_venv(venv: pathlib.Path) -> pathlib.Path | None:
    """Build a virtual environment at `venv` and hand back its interpreter.

    --system-site-packages on purpose. On a machine where the distribution
    already ships PyQt6 or numpy, a bare environment would have this project
    download its own copies of both and then run against them; inheriting
    what is already there means the environment holds only what is actually
    missing, which on the machines that need a venv at all is usually two or
    three small packages rather than a second Qt.
    """
    print(f"\nMaking a virtual environment in {venv} ...")
    try:
        subprocess.run([sys.executable, "-m", "venv",
                        "--system-site-packages", str(venv)], check=True)
    except Exception as exc:                                # noqa: BLE001
        say(BAD, "Virtual environment", f"could not be made ({exc})",
            "python3-venv may not be installed. On Debian and Ubuntu that is\n"
            "a separate package:\n"
            "    sudo apt install python3-venv")
        return None
    got = venv_python(venv)
    if not got.exists():
        say(BAD, "Virtual environment", f"no interpreter at {got}")
        return None
    say(OK, "Virtual environment", str(got))
    return got


# -- asking the person -----------------------------------------------------


class Asker:
    """Every yes/no in one place, so --check and a pipe cannot be got wrong.

    A prompt that nobody is there to answer must not be a prompt. With
    --check the answer is always no and nothing is installed; with no
    terminal on the other end the default stands, so this can be run from a
    script or a first-boot image without hanging on a question.
    """

    def __init__(self, check: bool, yes: bool, heavy: bool) -> None:
        self.check, self.yes, self.heavy = check, yes, heavy
        self.tty = sys.stdin is not None and sys.stdin.isatty()

    def ask(self, question: str, default: bool = True,
            spell_it: bool = False) -> bool:
        if self.check:
            print(f"    {question} -- not asked, this is a check only")
            return False
        if spell_it and not self.heavy and not self.tty:
            print(f"    {question} -- no, and nobody here to ask "
                  "(pass --heavy to mean it)")
            return False
        if self.yes and not spell_it:
            print(f"    {question} {'yes' if default else 'no'} (--yes takes "
                  "the answer in caps)")
            return default
        if self.heavy and spell_it and self.yes:
            print(f"    {question} yes (--yes --heavy)")
            return True
        if not self.tty:
            # No terminal and no --yes: this is a pipe, a hook or a first-boot
            # image, and none of those asked for anything to be installed.
            print(f"    {question} -- nobody here to ask, so no. "
                  "--yes means it.")
            return False
        hint = "type the word yes" if spell_it else ("Y/n" if default else "y/N")
        try:
            got = input(f"    {question} [{hint}] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if spell_it:
            return got == "yes"
        return default if not got else got.startswith("y")


# -- installing ------------------------------------------------------------


def pip_ready(python: pathlib.Path, ask: Asker) -> bool:
    got = subprocess.run([str(python), "-m", "pip", "--version"],
                         capture_output=True, text=True)
    if got.returncode == 0:
        say(OK, "pip", got.stdout.strip().split(" (")[0])
        return True
    say(WARN, "pip", "this Python has none",
        "Nothing can be installed without it. It ships with Python and can\n"
        "be put back from the standard library:\n"
        f"    {python} -m ensurepip --upgrade")
    if not ask.ask("Run ensurepip now?", default=True):
        return False
    return spawn([str(python), "-m", "ensurepip", "--upgrade"]) == 0


def install(python: pathlib.Path, pips: list[str], extra: list[str]) -> bool:
    """Hand the list to pip and let it draw its own progress.

    Not captured on purpose. A torch download is minutes long and a silent
    minute is indistinguishable from a hang, so pip's own output is the
    status here; this only says which command it was and what came of it.
    """
    cmd = [str(python), "-m", "pip", "install", *extra, *pips]
    print("\n    " + " ".join(cmd) + "\n")
    try:
        return spawn(cmd) == 0
    except KeyboardInterrupt:
        print("\n    stopped.")
        return False


def torch_index(m: dict, ask: Asker) -> list[str]:
    """Whether to ask pip for the CPU-only build of torch, and say why.

    Left as a question rather than decided, because it is the one install
    choice here that is expensive to get wrong in either direction: the
    default build brings the whole CUDA runtime, which is most of the
    download and useless without a card, while the CPU build on a machine
    that HAS one silently gives up the card the aligner was installed for.
    """
    if m["gpu"]:
        print(f"    This machine has {m['gpu']}, so the default (CUDA) build "
              "is the right one.")
        return []
    if m["arm_mac"]:
        print("    Apple Silicon: the ordinary wheel is the right one -- its "
              "GPU path (MPS) is in it.")
        return []
    print("    No NVIDIA card was found. The default wheel carries the CUDA "
          "runtime with it,\n    which is most of a 2-3 GB download and "
          "nothing this machine can use.")
    if ask.ask("Ask for the smaller CPU-only build instead?", default=True):
        return ["--index-url", "https://download.pytorch.org/whl/cpu"]
    return []


# -- programs that are not Python packages ---------------------------------


def package_manager() -> tuple[str, list[str]] | None:
    """This platform's own installer, as (name, command prefix).

    Only the user-level ones are ever offered to be RUN. A Linux install
    needs root, and a script that decides on its own to ask for root is a
    script that has taken a decision that was not its to take -- so those
    are printed instead.
    """
    if MAC and shutil.which("brew"):
        return "brew", ["brew", "install"]
    if WIN and shutil.which("winget"):
        return "winget", ["winget", "install", "-e", "--id"]
    for name, cmd in (("pacman", ["sudo", "pacman", "-S", "--needed"]),
                      ("apt", ["sudo", "apt", "install"]),
                      ("dnf", ["sudo", "dnf", "install"]),
                      ("zypper", ["sudo", "zypper", "install"])):
        if shutil.which(name):
            return name, cmd
    return None


PROGRAMS = {
    "yt-dlp": {
        "what": "fetching a song's audio, which is how the editor gets a "
                "waveform for a song it has no file for",
        "pip": "yt-dlp",
        "names": {"brew": "yt-dlp", "winget": "yt-dlp.yt-dlp", "apt": "yt-dlp",
                  "dnf": "yt-dlp", "pacman": "yt-dlp", "zypper": "yt-dlp"},
    },
    "ffmpeg": {
        "what": "animated album covers, and audio soundfile cannot read "
                "itself -- mp3, m4a, opus",
        "names": {"brew": "ffmpeg", "winget": "Gyan.FFmpeg", "apt": "ffmpeg",
                  "dnf": "ffmpeg", "pacman": "ffmpeg", "zypper": "ffmpeg"},
    },
    "espeak-ng": {
        "what": "the pronunciations phonemizer reads English syllables from",
        "names": {"brew": "espeak-ng", "winget": "eSpeak-NG.eSpeak-NG",
                  "apt": "espeak-ng", "dnf": "espeak-ng", "pacman": "espeak-ng",
                  "zypper": "espeak-ng"},
    },
}


def check_programs(python: pathlib.Path, extra: list[str],
                   can_install: bool, ask: Asker) -> None:
    """The programs this project runs rather than imports.

    None of them is a pip package by nature, so the line printed here is the
    package manager's rather than pip's. It is only OFFERED to be run where
    running it needs nobody's password: brew and winget install for the
    person who asked, while every Linux manager here wants root, and a
    script that decides on its own to ask for root has taken a decision that
    was not its to take.

    yt-dlp is the exception and gets offered through pip as well. It is pure
    Python, and it is the one program on this list that goes stale on a
    schedule somebody else sets -- when a site changes, a yt-dlp from the
    distribution can be months behind a working one.
    """
    mgr = package_manager()
    for exe, info in PROGRAMS.items():
        found = shutil.which(exe) or (shutil.which("espeak")
                                      if exe == "espeak-ng" else None)
        if found:
            say(OK, exe, found + ("  (the older espeak; phonemizer reads it "
                                  "the same way)"
                                  if exe == "espeak-ng"
                                  and not found.endswith("-ng") else ""))
            continue
        name, cmd, pkg, line = "", [], "", ""
        if mgr:
            name, cmd = mgr
            pkg = info["names"].get(name, exe)
            line = " ".join([*cmd, pkg])
        pip_line = (f"{python} -m pip install {' '.join(extra)} "
                    f"{info['pip']}".replace("  ", " ")
                    if info.get("pip") else "")
        say(WARN, exe, "not on PATH",
            f"Only needed for {info['what']}:\n"
            + "".join(f"    {x}\n" for x in (line, pip_line) if x)
            + ("" if line else
               "    (no package manager here this knows how to name it in)"))
        if info.get("pip") and can_install and ask.ask(
                f"Install {info['pip']} with pip now?", default=True):
            if install(python, [info["pip"]], extra):
                back = shutil.which(exe)
                say(OK if back else WARN, exe,
                    back or "installed, but not on PATH yet -- pip put it in\n"
                            "a scripts directory this shell has not looked in.")
            continue
        if not line or cmd[0] == "sudo":
            continue
        if ask.ask(f"Run {name} for {exe} now?", default=False):
            try:
                spawn([*cmd, pkg])
            except Exception as exc:                        # noqa: BLE001
                say(WARN, exe, f"{name} would not run ({exc})")
            else:
                back = shutil.which(exe)
                say(OK if back else WARN, exe,
                    back or "still not on PATH -- a new terminal may be "
                            "needed for PATH to catch up")


# -- does the window actually open -----------------------------------------


_QT_TEST = r'''
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
print(app.platformName() or "?")
'''


def check_qt_opens(python: pathlib.Path) -> None:
    """Whether Qt can start here, which importing PyQt6 does not answer.

    The failure this is for is the commonest one there is on Linux and the
    least self-explanatory: PyQt6 imports perfectly and then "could not load
    the Qt platform plugin xcb", because the plugin is there and the system
    libraries it links against are not. Nothing is shown -- a QApplication
    with no window on it draws nothing -- so this costs a second and puts no
    window over anybody's screen.
    """
    got = subprocess.run([str(python), "-c", _QT_TEST],
                         capture_output=True, text=True)
    if got.returncode == 0:
        say(OK, "Qt opens", f"platform plugin: {got.stdout.strip()}")
        return
    why = (got.stderr or got.stdout or "").strip().splitlines()
    headless = not WIN and not MAC and not os.environ.get("DISPLAY") \
        and not os.environ.get("WAYLAND_DISPLAY")
    if headless:
        say(WARN, "Qt opens", "no display on this session",
            "Not a broken install: there is no DISPLAY or WAYLAND_DISPLAY\n"
            "here, so Qt has no screen to open on. Run this again from the\n"
            "desktop session the app will be used in.")
        return
    say(BAD, "Qt opens", "PyQt6 imports, and cannot start",
        "\n".join(why[-4:]) + "\n"
        "The Python side is installed; what is missing is underneath it.\n"
        + ("On Debian and Ubuntu the usual answer is:\n"
           "    sudo apt install libxcb-cursor0 libxkbcommon-x11-0\n"
           "and QT_DEBUG_PLUGINS=1 names the library it could not find."
           if LINUX else
           "Reinstalling PyQt6 is the first thing to try:\n"
           f"    {python} -m pip install --force-reinstall PyQt6"))


# -- the run ---------------------------------------------------------------


def choose_python(args, ask: Asker) -> pathlib.Path | None:
    """Which interpreter everything below is checked and installed against.

    Four ways this can go, and the order matters. Already inside a virtual
    environment: use it, that is what it is for. Asked for one: make it.
    Found one sitting in the project: offer it, because a check run against
    the system Python on a machine that keeps its packages in .venv reports
    a pile of missing packages that are not missing. Otherwise this Python,
    whatever it is.
    """
    here = pathlib.Path(sys.executable)
    if in_venv(here):
        say(OK, "Environment", f"already in a virtual environment ({sys.prefix})")
        return here
    if args.venv:
        venv = pathlib.Path(args.venv) if isinstance(args.venv, str) \
            else ROOT / ".venv"
        if not venv_python(venv).exists():
            return make_venv(venv)
        say(OK, "Environment", f"using the one already at {venv}")
        return venv_python(venv)
    found = [p for p in sorted(ROOT.glob(".venv*")) if venv_python(p).exists()]
    if found:
        say(WARN, "Environment", f"this project has {found[0].name}",
            "A check run against the system Python on a machine that keeps\n"
            "this project's packages in there reports a pile of missing\n"
            "packages that are not missing.")
        if ask.ask(f"Check {found[0].name} rather than this Python?",
                   default=True):
            return venv_python(found[0])
    say(OK, "Environment", f"checking {here}")
    return here


def install_plan(python: pathlib.Path, args,
                 ask: Asker) -> tuple[pathlib.Path, list[str]] | None:
    """The extra pip arguments this machine needs, or None if it cannot.

    The externally-managed case is the whole of this function. On Arch,
    Debian, Fedora and the rest, the system Python's site-packages belongs
    to the distribution, pip refuses to write into it, and --user is refused
    with it -- so the two honest answers are a virtual environment or the
    distribution's own packages. --break-system-packages is the third, and
    is not offered here without being asked for by name, because what it
    breaks is the machine's own tools rather than this project.
    """
    if in_venv(python):
        return python, []
    if not managed(python):
        return python, ["--user"]
    if args.break_system_packages:
        say(WARN, "Install target", "the system Python, as asked",
            "--break-system-packages was passed. pip will write into the\n"
            "directory the distribution manages; its own packages and this\n"
            "install can now overwrite one another.")
        return python, ["--break-system-packages"]
    say(WARN, "Install target", "this Python belongs to the operating system",
        "It is marked externally managed (PEP 668), so pip will not write\n"
        "into it -- `pip install --user` is refused here too. Either let this\n"
        "make a virtual environment in the project, or install the packages\n"
        "through the distribution and run this again.")
    if ask.ask("Make a virtual environment in the project and use it?",
               default=True):
        got = make_venv(ROOT / ".venv")
        if got:
            print(f"\n    From here on the app runs with {got}.\n"
                  "    The launchers and doctor.py both use the interpreter "
                  "they are STARTED with,\n    so the desktop shortcuts have "
                  f"to be made with that one:\n"
                  f"        {got} {ROOT / 'mild-lyrics' / 'doctor.py'}\n")
            return got, []
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--check", action="store_true",
                    help="report only; never install anything and never ask")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="take the answer in CAPS at every prompt without "
                         "asking, which installs everything missing but the "
                         "heavy group -- that one is asked for by name, with "
                         "--heavy, and running doctor or a system package "
                         "manager is still left alone")
    ap.add_argument("--heavy", action="store_true",
                    help="allow the local-alignment group (torch, demucs and "
                         "what they bring) to be installed. With --yes it "
                         "installs without asking")
    ap.add_argument("--venv", nargs="?", const=True, metavar="PATH",
                    help="check and install into a virtual environment, made "
                         "if it is not there (default .venv in the project)")
    ap.add_argument("--break-system-packages", action="store_true",
                    help="on a distribution-managed Python, install into it "
                         "anyway. The alternative this offers instead is a "
                         "virtual environment")
    args = ap.parse_args()
    ask = Asker(args.check, args.yes, args.heavy)

    print("Mild Lyrics setup  --  "
          + ("Windows" if WIN else "macOS" if MAC else platform.system())
          + f" {platform.machine()}")
    print(f"{ROOT}\n")

    v = sys.version_info
    if v < MIN_PY:
        say(BAD, "Python", platform.python_version(),
            f"This needs {MIN_PY[0]}.{MIN_PY[1]} or newer. Nothing below can\n"
            "be checked against this one.")
        print(f"\n1 thing needs attention: Python {MIN_PY[0]}.{MIN_PY[1]}+")
        return 1
    say(OK, "Python", f"{platform.python_version()} at {sys.executable}")

    python = choose_python(args, ask)
    if python is None:
        return 1
    have_pip = pip_ready(python, ask)

    m = machine()
    say(OK, "This machine",
        f"{m['cores']} cores, {m['ram']:.1f} GB memory, "
        f"{m['free']:.1f} GB free here"
        + (f", {m['gpu']}" if m["gpu"] else
           ", Apple Silicon" if m["arm_mac"] else ", no NVIDIA card"))

    extra: list[str] = []
    if have_pip:
        plan = install_plan(python, args, ask)
        if plan is None:
            have_pip = False
        else:
            python, extra = plan

    print()
    for group in GROUPS:
        if not wanted(group):
            continue
        broken = report(group, probe(python, group.deps))
        if not broken or not have_pip:
            continue
        print()
        wrap(f"{group.title}: {group.why}")
        if group.need == "heavy":
            print()
            wrap("This is the big one. It is several gigabytes, and it is "
                 "the only thing here that can leave this machine worse "
                 "than it is now:")
            for line in misgivings(m):
                wrap(line, first="      - ", rest="        ")
            wrap("Nothing else in this project needs any of it: the "
                 "player and the editor both run without a line of it, and "
                 "every other group above is independent of this one.")
            if not ask.ask("Install it anyway?", spell_it=True):
                print("    Skipped. Running this again with --heavy offers "
                      "it once more.\n")
                continue
            # Only this group's install. The CPU index carries torch and
            # what torch is built with, and nothing else -- asking it for
            # phonemizer afterwards would look for a package that is not
            # there and fail on a package that is fine.
            group_extra = extra + torch_index(m, ask)
        elif not ask.ask(f"Install {', '.join(d.pip for d in broken)}?",
                         default=True):
            print()
            continue
        else:
            group_extra = extra
        if not install(python, [d.pip for d in broken], group_extra):
            say(BAD, f"{group.title}: install",
                "pip did not finish cleanly",
                "Its own output above says why. Nothing here retries it: a\n"
                "second identical attempt fails identically.")
            print()
            continue
        print("    Installed. Asking a fresh interpreter whether it works:\n")
        again = probe(python, tuple(broken))
        for dep in broken:
            row = again.get(dep.module, {})
            if row.get("ok") and not row.get("broke"):
                _fails[:] = [f for f in _fails
                             if f != f"{group.title}: {dep.pip}"]
                _warns[:] = [w for w in _warns
                             if w != f"{group.title}: {dep.pip}"]
                say(OK, f"{group.title}: {dep.pip}",
                    " ".join(x for x in (row.get("version", ""),
                                         row.get("note", "")) if x)
                    or "installed and imports")
            else:
                say(BAD, f"{group.title}: {dep.pip}",
                    "installed, and still does not work",
                    (row.get("crash") and
                     "pip put it there and importing it kills the "
                     "interpreter.\nThis wheel is wrong for this machine; the "
                     "package is not\nthe problem and reinstalling it will "
                     "not change this.")
                    or row.get("broke") or row.get("why", ""))
        print()

    print()
    check_programs(python, extra, have_pip, ask)

    qt = probe(python, GROUPS[0].deps)
    if all(row.get("ok") for row in qt.values()):
        check_qt_opens(python)

    print()
    if _fails:
        print(f"{len(_fails)} thing(s) need attention: "
              f"{', '.join(dict.fromkeys(_fails))}")
    elif _warns:
        print("Nothing is missing that either program needs. Left with a "
              "warning above:\n    " + ", ".join(dict.fromkeys(_warns)))
    else:
        print("Everything on the list is installed and works.")

    runner = str(python.with_name("pythonw.exe")
                 if WIN and python.with_name("pythonw.exe").exists()
                 else python)
    print("\nStart it with:")
    print(f"    {runner} {ROOT / 'mild-lyrics.pyw'}")
    print(f"    {runner} {ROOT / 'ttml-editor.pyw'}")
    print("\nThe rest of the setup -- players, the Spotify debug port, caches,\n"
          "and the desktop shortcuts -- is doctor.py:")
    print(f"    {python} {ROOT / 'mild-lyrics' / 'doctor.py'}")
    if ask.ask("Run it now?", default=False):
        print()
        spawn([str(python), str(ROOT / "mild-lyrics" / "doctor.py")])
    return 1 if _fails else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nstopped.")
        raise SystemExit(1)
