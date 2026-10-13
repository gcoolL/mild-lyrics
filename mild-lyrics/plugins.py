"""Plugins: code somebody installs after the app, into its config folder.

A plugin is a folder under <config>/plugins/ with a plugin.json (what it is,
its settings, its permissions) and an __init__.py with start(api) and
optionally stop(). docs/plugins/README.md is the guide for writing one.

Each switched-on plugin runs in a process of its own (plugin_runner), walled
in by plugin_sandbox before its code loads: it reads its own folder, writes
its own data folder, reaches only the sites it lists through plugin_proxy,
and gets what else it asks for in "permissions" once it has been allowed.
Messages both ways are JSON lines; nothing here waits on a plugin.
"""

from __future__ import annotations

import collections
import concurrent.futures
import importlib.util
import io
import json
import os
import pathlib
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

API_VERSION = 2
KINDS = ("bool", "choice", "num", "text", "secret", "action")
# Keys the menu knows a plugin's rows by: "plug.<id>" is its switch,
# "plug.<id>.<key>" one of its settings.
PREFIX = "plug."
HOST_KEYS = ("plugins_browse", "plugins_folder", "plugins_install",
             "plugins_submit")
ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
VERSION_RE = re.compile(r"[0-9A-Za-z.+-]{1,32}")
SITE_RE = re.compile(r"(\*\.)?([a-z0-9-]+\.)+[a-z]{2,63}")
PERMISSIONS = ("network", "player", "spotify", "listen", "folders")
# Left out of a plugin's zip, whoever makes it.
PACK_SKIP_DIRS = {"__pycache__", ".git", "tests"}
PACK_SKIP_ENDS = (".pyc", ".pyo")
UNPACKED_MAX = 50 * 1024 * 1024
MAX_LINE = 4 * 1024 * 1024
RUNNER = pathlib.Path(__file__).resolve().parent / "plugin_runner.py"

_ROOT: pathlib.Path | None = None
_PLUGINS: dict[str, "Plugin"] = {}
_state = None              # () -> the playback dict, given by the window
_toast = None              # (text) -> None, given by the window
_control = None            # (name, value) -> None, given by the window
_spotify = None            # (expression) -> value, given by the window
_lyrics = None             # () -> the playing song's lyrics, given by the window
_notes: dict = {}          # drawer section name -> its plugin's "note"
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2,
                                              thread_name_prefix="plugin-spotify")
CONTROLS = ("PlayPause", "Next", "Previous", "seek", "volume", "open")


def _log(*bits) -> None:
    print("[plugins]", *bits, file=sys.stderr, flush=True)


def _top_names(lib: pathlib.Path) -> list[str]:
    """The modules and packages a plugin's lib/ holds, by import name."""
    out = []
    for e in lib.iterdir():
        name = e.name.split(".")[0]
        if (name.isidentifier() and not name.startswith("_")
                and (e.is_dir() or e.suffix in (".py", ".so", ".pyd"))):
            out.append(name)
    return sorted(set(out))


def _hidden(lib: pathlib.Path) -> list[tuple[str, str]]:
    """(name, where) for each lib/ module an import would find elsewhere."""
    out = []
    for name in _top_names(lib):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            continue
        if spec is None:
            continue
        where = spec.origin if spec.origin not in (None, "built-in", "frozen") \
            else next(iter(spec.submodule_search_locations or []), spec.origin)
        try:
            ours = pathlib.Path(str(where)).resolve().is_relative_to(lib.resolve())
        except (OSError, ValueError):
            ours = False
        if not ours:
            out.append((name, str(where)))
    return out


def folder() -> pathlib.Path:
    return (_ROOT or pathlib.Path(".")) / "plugins"


def data_folder() -> pathlib.Path:
    return (_ROOT or pathlib.Path(".")) / "plugin-data"


def kernel_walls() -> bool:
    """Whether this system fences a plugin in at the kernel (Linux Landlock)."""
    import plugin_sandbox as SB
    return SB.landlock_abi() >= 1


# ---------------------------------------------------------------- manifests
def _check_permissions(m: dict, keys: set) -> None:
    perms = m.get("permissions") or {}
    if not isinstance(perms, dict):
        raise ValueError("permissions is not an object")
    for k in perms:
        if k not in PERMISSIONS:
            raise ValueError(f"permission {k!r} is not one of {', '.join(PERMISSIONS)}")
    sites = perms.get("network") or []
    if not isinstance(sites, list) or not all(
            isinstance(s, str) and SITE_RE.fullmatch(s) for s in sites):
        raise ValueError("network lists sites, like example.com or *.example.com")
    for k in ("player", "spotify", "listen"):
        if not isinstance(perms.get(k, False), bool):
            raise ValueError(f"permission {k} is true or false")
    for f in perms.get("folders") or []:
        if not isinstance(f, dict) or f.get("access") not in ("read", "write"):
            raise ValueError("a folder needs access: read or write")
        if not re.fullmatch(r"(config|home):[^\0]+", str(f.get("path") or "")) \
                or ".." in pathlib.PurePosixPath(str(f["path"]).split(":", 1)[1]).parts:
            raise ValueError("a folder's path is config:<folder> or home:<folder>")
        if "setting" in f and f["setting"] not in keys:
            raise ValueError(f"a folder names setting {f['setting']!r}, which it lacks")
        if ".." in pathlib.PurePosixPath(str(f.get("within") or "")).parts:
            raise ValueError("a folder's within stays inside it")


def _read_manifest(d: pathlib.Path) -> dict:
    """plugin.json, checked. Raises ValueError saying what is wrong."""
    try:
        m = json.loads((d / "plugin.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("no plugin.json") from None
    except (OSError, ValueError) as e:
        raise ValueError(f"plugin.json unreadable: {e}") from None
    if not isinstance(m, dict):
        raise ValueError("plugin.json is not an object")
    pid = str(m.get("id") or "")
    if not ID_RE.fullmatch(pid):
        raise ValueError(f"id {pid!r}: lower-case letters, digits, - and _")
    try:
        api = int(m.get("api", 1))
    except (TypeError, ValueError):
        raise ValueError("api is not a number") from None
    if api > API_VERSION:
        raise ValueError(f"needs plugin API {api}; this app has "
                         f"{API_VERSION}. Update Mild Lyrics")
    rows = m.get("settings") or []
    if not isinstance(rows, list):
        raise ValueError("settings is not a list")
    keys = set()
    for s in rows:
        if not isinstance(s, dict):
            raise ValueError("a setting is not an object")
        if "heading" in s:
            continue
        key, kind = str(s.get("key") or ""), s.get("kind")
        if not ID_RE.fullmatch(key) or key in keys:
            raise ValueError(f"setting key {key!r} is bad or repeated")
        if kind not in KINDS:
            raise ValueError(f"setting {key}: kind {kind!r} is not one of "
                             f"{', '.join(KINDS)}")
        if kind == "choice" and not s.get("choices"):
            raise ValueError(f"setting {key}: a choice needs choices")
        if kind == "num" and not all(k in s for k in ("min", "max", "step")):
            raise ValueError(f"setting {key}: a num needs min, max and step")
        keys.add(key)
    _check_permissions(m, keys)
    if not (d / "__init__.py").is_file():
        raise ValueError("no __init__.py")
    return m


def permissions(m: dict) -> dict:
    """A manifest's permissions, every key present."""
    p = m.get("permissions") or {}
    return {"network": sorted(p.get("network") or []),
            "player": bool(p.get("player")), "spotify": bool(p.get("spotify")),
            "listen": bool(p.get("listen")), "folders": list(p.get("folders") or [])}


def describe(m: dict) -> list[str]:
    """What a plugin may do, in words, for the question before it runs."""
    p = permissions(m)
    out = []
    if p["network"]:
        out.append("Connect to " + ", ".join(p["network"]) + " (and nowhere else)")
    if p["player"]:
        out.append("Control playback: play, pause, skip, seek, volume")
    if p["spotify"]:
        out.append("Run scripts inside Spotify's app, which can do anything your "
                   "Spotify account can")
    if p["listen"]:
        out.append("Accept connections from other apps on this computer")
    for f in p["folders"]:
        where = f["path"].replace("config:", "your config folder/").replace(
            "home:", "~/")
        out.append(("Read and write " if f["access"] == "write" else "Read ") + where
                   + (f" (or the folder set in “{f['setting']}”)" if f.get("setting")
                      else ""))
    return out or ["Nothing beyond its own folder and settings"]


def walls_said() -> str:
    if kernel_walls():
        return ("It runs walled in by the system: it can't touch your other files, "
                "run programs or reach anything it doesn't list.")
    return ("This system can't wall plugins in. It runs in its own process behind "
            "checks that a plugin written to get past them could get past.")


def _spec(s: dict):
    kind = s["kind"]
    if kind == "choice":
        return [str(c) for c in s["choices"]]
    if kind == "num":
        lo, hi, step = s["min"], s["max"], s["step"]
        whole = all(isinstance(v, int) for v in (lo, hi, step))
        fmt = str(s.get("format") or ("{:.0f}" if whole else "{:.2f}"))
        return (lo, hi, step, fmt)
    return None


def _fallback(s: dict):
    kind = s["kind"]
    if kind == "bool":
        return False
    if kind == "choice":
        return str(s["choices"][0])
    if kind == "num":
        return s["min"]
    return ""


def _clean(s: dict, v):
    """A stored or typed value as its setting allows, else its default."""
    kind = s["kind"]
    default = s.get("default", _fallback(s))
    try:
        if kind == "bool":
            return bool(v)
        if kind == "choice":
            return str(v) if str(v) in [str(c) for c in s["choices"]] else default
        if kind == "num":
            x = min(s["max"], max(s["min"], float(v)))
            return int(round(x)) if isinstance(s["step"], int) else x
        if kind in ("text", "secret"):
            return str(v if v is not None else "")
    except (TypeError, ValueError):
        return default
    return None


def _config_base() -> pathlib.Path:
    home = pathlib.Path.home()
    if sys.platform == "win32":
        return pathlib.Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return home / "Library" / "Application Support"
    return pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")


def grant_path(f: dict, values: dict) -> pathlib.Path:
    """Where a folder permission points, refusing anywhere too wide: the home
    or config folder themselves, anything above them, and Mild Lyrics' own."""
    if f.get("setting") and str(values.get(f["setting"]) or "").strip():
        p = pathlib.Path(str(values[f["setting"]]).strip()).expanduser() / str(
            f.get("within") or "")
    else:
        kind, _, rel = f["path"].partition(":")
        p = (_config_base() if kind == "config" else pathlib.Path.home()) / rel
    p = pathlib.Path(os.path.realpath(p))
    home, base = (pathlib.Path(os.path.realpath(x))
                  for x in (pathlib.Path.home(), _config_base()))
    mine = pathlib.Path(os.path.realpath(_ROOT)) if _ROOT else None
    if not p.is_absolute() or any(p == x or x.is_relative_to(p) for x in (home, base)):
        raise ValueError(f"{p} is too wide to hand a plugin")
    if mine is not None and (p.is_relative_to(mine) or mine.is_relative_to(p)):
        raise ValueError(f"{p} holds Mild Lyrics' own files")
    return p


def _owner(f: dict, values: dict) -> pathlib.Path:
    """The folder a permission's folder lives in (the other app's own): a
    write grant's folder is made only once that exists."""
    if f.get("setting") and str(values.get(f["setting"]) or "").strip():
        return pathlib.Path(str(values[f["setting"]]).strip()).expanduser()
    kind, _, rel = f["path"].partition(":")
    first = pathlib.PurePosixPath(rel).parts[0]
    return (_config_base() if kind == "config" else pathlib.Path.home()) / first


# ------------------------------------------------------------------ plugins
class Plugin:
    def __init__(self, d: pathlib.Path, m: dict) -> None:
        self.dir, self.manifest = d, m
        self.id = m["id"]
        self.name = str(m.get("name") or self.id)
        self.version = str(m.get("version") or "")
        self.about = str(m.get("description") or "")
        self.settings = {s["key"]: s for s in m.get("settings") or []
                         if "heading" not in s}
        self.running = False
        self.error = ""
        self.stale = False                  # its files were replaced under it
        self.removed = False                # uninstalled; its rows stay till restart
        self.level = ""                     # "kernel" or "guards", once it said
        self.status_text = ""
        self.proc = None
        self._lock = threading.Lock()
        self._inbox: collections.deque = collections.deque()
        self._out: queue.Queue | None = None
        self._wants: set = set()
        self._lyrics_key = None
        self._proxy = ""
        self._tail: collections.deque = collections.deque(maxlen=8)
        self._toasted = 0.0
        self._file = data_folder() / self.id / "settings.json"
        self.values = self._load()

    # -- stored values
    def _load(self) -> dict:
        try:
            got = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = {}
        if not isinstance(got, dict):
            got = {}
        out = {"on": bool(got.get("on", self.manifest.get("on", False)))}
        for k in ("_granted", "_unguarded"):
            if k in got:
                out[k] = got[k]
        for k, s in self.settings.items():
            if s["kind"] != "action":
                out[k] = _clean(s, got.get(k, s.get("default", _fallback(s))))
        return out

    def save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                tmp = self._file.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.values, indent=2), encoding="utf-8")
                tmp.chmod(0o600)            # a secret row is kept in here
                tmp.replace(self._file)
        except OSError as e:
            _log(self.id, "could not save settings:", e)

    def settings_values(self) -> dict:
        return {k: v for k, v in self.values.items() if k in self.settings}

    def put(self, key: str, value) -> None:
        s = self.settings.get(key)
        if s is None or s["kind"] == "action":
            raise KeyError(key)
        value = _clean(s, value)
        if self.values.get(key) == value:
            return
        self.values[key] = value
        self.save()
        self.send(t="changed", key=key, value=value)

    # -- what it is allowed
    def granted(self) -> bool:
        return self.values.get("_granted") == permissions(self.manifest)

    def allowed(self) -> bool:
        """Its permissions allowed, and -- where the system can't wall it in --
        running without the walls allowed too."""
        return self.granted() and (kernel_walls() or bool(self.values.get("_unguarded")))

    def grant(self) -> None:
        self.values["_granted"] = permissions(self.manifest)
        if not kernel_walls():
            self.values["_unguarded"] = True
        self.save()

    def walls(self) -> dict:
        import plugin_sandbox as SB
        perms = permissions(self.manifest)
        data = self._file.parent
        read = SB.python_paths() + [str(RUNNER.parent), str(self.dir), "/dev/urandom"]
        write = [str(data), "/dev/null"]
        for f in perms["folders"]:
            p = grant_path(f, self.values)
            if f["access"] == "write" and not p.exists() and _owner(f, self.values).is_dir():
                p.mkdir(parents=True, exist_ok=True)    # a grant needs a folder to hold
            (write if f["access"] == "write" else read).append(str(p))
        return {"read": read, "write": write, "listen": perms["listen"],
                "proxy_port": 0}

    # -- running
    def send(self, **msg) -> None:
        """To the plugin's process, without waiting: a backed-up plugin loses
        playback updates rather than holding the window up."""
        out = self._out
        if out is None or not self.running:
            return
        try:
            out.put_nowait(msg)
        except queue.Full:
            if msg.get("t") != "playback":
                _log(self.id, "is not keeping up; a message was dropped")

    def start(self) -> None:
        if self.running or self.stale or self.removed:
            return
        self.error, self.status_text, self.level = "", "", ""
        if not self.allowed():
            self.error = "needs your OK · switch it off and on"
            return
        lib = self.dir / "lib"
        if lib.is_dir():
            app = pathlib.Path(__file__).resolve().parent
            for name, where in _hidden(lib):
                if pathlib.Path(where).resolve().parent == app:
                    self.error = f"lib/{name} is hidden by Mild Lyrics' own {name}"
                    return
                _log(self.id, f"lib/{name} is not used: {where} is found first")
        try:
            walls = self.walls()
        except ValueError as e:
            self.error = str(e)
            return
        perms = permissions(self.manifest)
        data = self._file.parent
        (data / "tmp").mkdir(parents=True, exist_ok=True)
        # Where things are, as names only: the walls decide what it may open.
        env = {"TMPDIR": str(data / "tmp"), "TEMP": str(data / "tmp"),
               "TMP": str(data / "tmp"), "LANG": os.environ.get("LANG", "C.UTF-8"),
               "PYTHONIOENCODING": "utf-8"}
        for k in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA",
                  "SYSTEMROOT", "WINDIR", "LC_ALL", "PATH"):
            if k in os.environ:
                env[k] = os.environ[k]
        if perms["network"]:
            import plugin_proxy as PX
            self._proxy = PX.admit(self.id, perms["network"],
                                   lambda why: _log(self.id, "network refused:", why))
            walls["proxy_port"] = PX.port()
            for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
                env[k] = self._proxy
        spec = {"id": self.id, "dir": str(self.dir), "data": str(data),
                "api_version": API_VERSION, "values": self.settings_values(),
                "perms": perms, "walls": walls, "kernel": kernel_walls(),
                "path": [str(RUNNER.parent)] + [p for p in sys.path if p]}
        flags = 0x08000000 if sys.platform == "win32" else 0     # CREATE_NO_WINDOW
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-I", "-B", str(RUNNER)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(data),
                env=env, close_fds=True, creationflags=flags)
            self.proc.stdin.write((json.dumps(spec) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError as e:
            self.error = f"could not start: {e}"
            self._forget_proxy()
            return
        self._inbox = collections.deque()       # this process's own: an old one's
        self._wants, self._lyrics_key = set(), None   # last words can't land here
        self._out = queue.Queue(maxsize=256)
        self.running = True
        proc = self.proc
        threading.Thread(target=self._read, args=(proc, self._inbox), daemon=True,
                         name=f"plugin-{self.id}-out").start()
        threading.Thread(target=self._read_err, args=(proc,), daemon=True,
                         name=f"plugin-{self.id}-err").start()
        threading.Thread(target=self._write, args=(proc, self._out), daemon=True,
                         name=f"plugin-{self.id}-in").start()
        _log(self.id, "started", self.version)

    @staticmethod
    def _read(proc, inbox: collections.deque) -> None:
        for raw in proc.stdout:
            if len(raw) > MAX_LINE:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict):
                inbox.append(msg)
        inbox.append({"t": "exited"})

    def _read_err(self, proc) -> None:
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()[:2000]
            if line:
                self._tail.append(line)
                _log(self.id, line)

    @staticmethod
    def _write(proc, out: queue.Queue) -> None:
        while True:
            msg = out.get()
            if msg is None:
                break
            try:
                proc.stdin.write((json.dumps(msg, default=str) + "\n").encode("utf-8"))
                proc.stdin.flush()
            except (OSError, ValueError):
                break
            if msg.get("t") == "stop":
                break
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    def _forget_proxy(self) -> None:
        if self._proxy:
            import plugin_proxy as PX
            PX.forget(self._proxy)
            self._proxy = ""

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        proc, out = self.proc, self._out
        self._out = None
        if out is not None:
            try:
                out.put_nowait({"t": "stop"})
            except queue.Full:
                out = None
        self._forget_proxy()

        def reap():
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        threading.Thread(target=reap, daemon=True).start()

    def fail(self, why: str) -> None:
        self.error = why.splitlines()[0][:200] if why else "failed"
        _log(self.id, "stopped:", self.error)
        self.stop()

    def tick(self, playback) -> None:
        """On the GUI thread: what the plugin asked for, then what it hears."""
        while self._inbox and self.running:
            self._handle(self._inbox.popleft())
        if not self.running:
            return
        if "playback" in self._wants:
            self.send(t="playback", data=playback())
        if "lyrics" in self._wants and _lyrics:
            try:
                lyr = _lyrics()
            except Exception:                            # noqa: BLE001
                lyr = None
            key = None if lyr is None else (lyr.get("tid"), lyr.get("state"),
                                            id(lyr.get("doc")))
            if key != self._lyrics_key:
                self._lyrics_key = key
                self.send(t="lyrics", data=lyr)

    def _handle(self, msg: dict) -> None:
        t = msg.get("t")
        perms = permissions(self.manifest)
        if t == "ready":
            self.level = str(msg.get("level"))
            if self.level != "kernel" and kernel_walls():
                self.fail("the system's walls could not be put up")
        elif t == "status":
            self.status_text = str(msg.get("text") or "")[:200]
        elif t == "set":
            try:
                self.put(str(msg.get("key")), msg.get("value"))
            except KeyError:
                _log(self.id, "tried to set", str(msg.get("key"))[:60])
        elif t == "reset":
            for k, s in self.settings.items():
                if s["kind"] != "action":
                    self.put(k, s.get("default", _fallback(s)))
        elif t == "toast":
            now = time.monotonic()
            if _toast and now - self._toasted > 1.0:
                self._toasted = now
                _toast(f"{self.name}: {str(msg.get('text'))[:300]}")
        elif t == "log":
            _log(self.id, str(msg.get("text"))[:4000])
        elif t == "want" and msg.get("what") in ("playback", "lyrics"):
            self._wants.add(msg["what"])
        elif t == "control":
            name = msg.get("name")
            if perms["player"] and name in CONTROLS and _control:
                try:
                    _control(name, msg.get("value"))
                except Exception as e:                   # noqa: BLE001
                    _log(self.id, f"control {name} raised: {e}")
        elif t == "spotify":
            self._spotify(msg, perms)
        elif t == "failed":
            self.fail(str(msg.get("why") or "failed"))
        elif t == "exited":
            if self.running:
                tail = next((x for x in reversed(self._tail) if x.strip()), "")
                self.fail(f"its process ended{': ' + tail if tail else ''}")

    def _spotify(self, msg: dict, perms: dict) -> None:
        rid = msg.get("id")
        if not perms["spotify"]:
            self.send(t="reply", id=rid, ok=False, kind="script",
                      error="this plugin did not ask to run scripts in Spotify")
            return
        js = str(msg.get("js") or "")[:1_000_000]

        def run():
            try:
                if not _spotify:
                    raise ConnectionError("Mild Lyrics has no Spotify page to ask")
                self.send(t="reply", id=rid, ok=True, value=_spotify(js))
            except (ConnectionError, OSError) as e:
                self.send(t="reply", id=rid, ok=False, kind="connection", error=str(e))
            except Exception as e:                       # noqa: BLE001
                self.send(t="reply", id=rid, ok=False, kind="script", error=str(e))
        _pool.submit(run)

    def said(self) -> str:
        """What the switch's row reads beside on/off."""
        if self.removed:
            return "removed · restart Mild Lyrics"
        if self.stale:
            return "updated · restart Mild Lyrics"
        if self.error:
            return f"failed · {self.error}"
        store = sys.modules.get("plugin_store")
        new = store.update_for(self.id, self.version) if store else None
        more = f" · {new['version']} in Browse plugins" if new else ""
        if not self.values["on"]:
            return "off" + more
        if not self.running:
            return "on" + more
        text = self.status_text
        return (f"on · {text}" if text else "on") + more

    def reload(self) -> bool:
        """Take up new files in place. False when only a restart can: the menu
        was built from its old settings and name."""
        try:
            m = _read_manifest(self.dir)
        except ValueError:
            return False
        if (m.get("settings") != self.manifest.get("settings")
                or m.get("name") != self.manifest.get("name")):
            return False
        was = self.running
        self.stop()
        self.manifest, self.stale = m, False
        self.version = str(m.get("version") or "")
        self.about = str(m.get("description") or "")
        if was or self.values["on"]:
            self.start()
        return True


# --------------------------------------------------------------- discovery
def load(root: pathlib.Path, state=None, toast=None) -> None:
    """Find the installed plugins. Nothing runs here: that waits for
    start_all(), and for a switched-off plugin, for its switch."""
    global _ROOT, _state, _toast
    _ROOT, _state, _toast = pathlib.Path(root), state, toast
    _PLUGINS.clear()
    try:
        dirs = sorted(p for p in folder().iterdir() if p.is_dir())
    except OSError:
        return
    for d in dirs:
        if d.name.startswith((".", "_")):
            continue
        try:
            m = _read_manifest(d)
        except ValueError as e:
            _log(f"skipped {d.name}: {e}")
            continue
        if m["id"] in _PLUGINS:
            _log(f"skipped {d.name}: id {m['id']} is already {_PLUGINS[m['id']].dir.name}")
            continue
        _PLUGINS[m["id"]] = Plugin(d, m)


def attach(state, toast, control=None, spotify=None, lyrics=None) -> None:
    """The window's playback reader, toaster, player controls, Spotify page
    and lyrics, once it has them."""
    global _state, _toast, _control, _spotify, _lyrics
    _state, _toast, _control, _spotify, _lyrics = (state, toast, control,
                                                   spotify, lyrics)


def plugins() -> list[Plugin]:
    return list(_PLUGINS.values())


def start_all() -> None:
    for p in _PLUGINS.values():
        if p.values["on"]:
            p.start()


def stop_all() -> None:
    for p in _PLUGINS.values():
        p.stop()


def tick() -> None:
    cache: list = []

    def playback():
        if not cache:
            try:
                cache.append(_state() if _state else {})
            except Exception as e:                       # noqa: BLE001
                _log("reading playback raised:", e)
                cache.append({})
        return cache[0]

    for p in _PLUGINS.values():
        if p.running:
            p.tick(playback)


# -------------------------------------------------------------------- menu
def _section_name(p: Plugin, taken: set) -> str:
    name = p.name if p.name not in taken else f"{p.name} (plugin)"
    taken.add(name)
    return name


def menu_sections(taken: set) -> tuple[list, dict]:
    """(MENU_SECTIONS entries, DRAWER_ORDER entries): a Plugins tab with the
    folder and installer, then one tab per plugin -- its switch and then its
    settings in plugin.json's order, headings included."""
    sections = [("Plugins", [
        ("Browse plugins", "plugins_browse", "action", None),
        ("Plugins folder", "plugins_folder", "action", None),
        ("Install a plugin", "plugins_install", "action", None),
        ("Submit a plugin", "plugins_submit", "action", None),
    ])]
    order = {}
    _notes.clear()
    for p in _PLUGINS.values():
        name = _section_name(p, taken)
        if p.manifest.get("note"):
            _notes[name] = str(p.manifest["note"])
        rows = [(p.name, PREFIX + p.id, "bool", None)]
        keys = [PREFIX + p.id]
        for s in p.manifest.get("settings") or []:
            if "heading" in s:
                keys.append(("h", str(s["heading"])))
                continue
            key = f"{PREFIX}{p.id}.{s['key']}"
            rows.append((str(s.get("label") or s["key"]), key, s["kind"],
                         _spec(s)))
            keys.append(key)
        sections.append((name, rows))
        order[name] = keys
    return sections, order


def note(section: str) -> str:
    """The line under a plugin's tab title, from its plugin.json."""
    return _notes.get(section, "")


def owns(key) -> bool:
    return isinstance(key, str) and (key.startswith(PREFIX) or key in HOST_KEYS)


def _split(key: str) -> tuple[Plugin | None, str | None]:
    rest = key[len(PREFIX):]
    pid, _, sub = rest.partition(".")
    return _PLUGINS.get(pid), (sub or None)


def text_keys() -> dict:
    """{menu key: hint} for every text and secret row, for the text box."""
    out = {}
    for p in _PLUGINS.values():
        for k, s in p.settings.items():
            if s["kind"] in ("text", "secret"):
                out[f"{PREFIX}{p.id}.{k}"] = str(
                    s.get("hint") or f"{p.name}: {s.get('label') or k}")
    return out


def value(key: str):
    if key in HOST_KEYS:
        return None
    p, sub = _split(key)
    if p is None:
        return None
    if sub is None:
        return p.values["on"] and not p.error
    s = p.settings.get(sub)
    return None if s is None or s["kind"] == "action" else p.values.get(sub)


def change(key: str, value) -> None:
    p, sub = _split(key)
    if p is None:
        return
    if sub is None:
        on = bool(value)
        p.values["on"] = on
        p.save()
        if on and (p.stale or p.removed):
            if _toast:
                _toast(f"{p.name} was {'removed' if p.removed else 'updated'}"
                       " · restart Mild Lyrics")
        elif on and not p.allowed():
            p.values["on"] = False
            p.save()

            def ok(_d=None):
                p.grant()
                change(key, True)
            import plugin_store as ST
            ST.ask({"title": f"Let {p.name} run?",
                    "body": [f"{p.name} {p.version} asks to:"]
                    + [f"• {line}" for line in describe(p.manifest)] + [walls_said()],
                    "yes": "Allow", "default_no": True, "ok": ok})
        elif on:
            p.error = ""
            p.start()
            if p.error and _toast:
                _toast(f"{p.name} failed: {p.error}")
        else:
            p.error = ""
            p.stop()
        return
    if sub in p.settings:
        p.put(sub, value)


def said(key: str) -> str | None:
    """What the Plugins rows and a plugin's switch read beside their labels;
    None for a plugin's own settings, which read as any row of their kind."""
    if key == "plugins_folder":
        n = len(_PLUGINS)
        return f"{n} installed" if n else "none installed"
    if key == "plugins_install":
        return "folder or .zip"
    if key == "plugins_browse":
        import plugin_store
        return plugin_store.said()
    if key == "plugins_submit":
        return "for the marketplace"
    p, sub = _split(key)
    if p is None:
        return ""
    return p.said() if sub is None else None


def verb(key: str) -> str:
    if key == "plugins_folder":
        return "Open"
    if key == "plugins_install":
        return "Install…"
    if key == "plugins_browse":
        return "Browse…"
    if key == "plugins_submit":
        return "Submit…"
    p, sub = _split(key)
    s = p.settings.get(sub) if p is not None and sub else None
    return str((s or {}).get("verb") or "Run")


def run(key: str) -> None:
    """An action row was pressed."""
    if key == "plugins_folder":
        open_folder()
        return
    if key == "plugins_install":
        pick_and_install()
        return
    if key == "plugins_browse":
        import plugin_store
        plugin_store.browse()
        return
    if key == "plugins_submit":
        import plugin_store
        plugin_store.pick_and_submit()
        return
    p, sub = _split(key)
    if p is None or sub is None:
        return
    if not p.running:
        if _toast:
            _toast(f"{p.name}: switch it on first")
        return
    p.send(t="action", key=sub)


# ---------------------------------------------------------------- installs
def open_folder() -> None:
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    folder().mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder())))


def pick_and_install() -> None:
    import plugin_store as ST
    from PyQt6.QtWidgets import QFileDialog
    path, _f = QFileDialog.getOpenFileName(
        None, "Install a plugin: its .zip, or the plugin.json in its folder",
        str(pathlib.Path.home()), "Plugins (*.zip plugin.json)")
    if not path:
        return
    try:
        m = peek(pathlib.Path(path))
    except ValueError as e:
        ST.tell("Not a plugin", str(e))
        return

    def go():
        try:
            where = install(pathlib.Path(path), grant=True)
        except (OSError, ValueError) as e:
            ST.tell("Not installed", str(e))
            return
        if _toast:
            _toast(f"installed into {where.name} · restart Mild Lyrics to see it")
    confirm(m, go)


def confirm(m: dict, then) -> None:
    """What it may do, asked before it is installed; then() on yes. A yes
    allows those permissions (install(..., grant=True) keeps the answer)."""
    import plugin_store as ST
    name = m.get("name") or m["id"]
    ST.ask({"title": f"Install {name}?",
            "body": [f"{name} {m.get('version') or ''}: {m.get('description') or ''}",
                     "It asks to:"] + [f"• {line}" for line in describe(m)]
            + [walls_said()],
            "yes": "Install", "default_no": True, "ok": lambda _d: then()})


def _unpacked(path: pathlib.Path, into: pathlib.Path) -> pathlib.Path:
    """The plugin folder `path` names: a plugin.json's folder, a folder, or a
    .zip unpacked under `into` (whose plugin.json may sit one level down)."""
    if path.name == "plugin.json":
        return path.parent
    if path.is_dir():
        return path
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            t = pathlib.PurePosixPath(n)
            if t.is_absolute() or ".." in t.parts:
                raise ValueError(f"the zip holds a path outside itself: {n}")
        if sum(i.file_size for i in z.infolist()) > UNPACKED_MAX:
            raise ValueError("the zip unpacks to more than 50 MB")
        z.extractall(into)
    if (into / "plugin.json").is_file():
        return into
    inner = [d for d in into.iterdir() if d.is_dir()]
    if len(inner) == 1 and (inner[0] / "plugin.json").is_file():
        return inner[0]
    raise ValueError("no plugin.json at the top of the zip, or in the one "
                     "folder it holds")


def pack_files(d: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in d.rglob("*") if p.is_file()
                  and not PACK_SKIP_DIRS.intersection(p.relative_to(d).parts)
                  and not p.name.endswith(PACK_SKIP_ENDS))


def pack(d: pathlib.Path, pid: str) -> bytes:
    """The folder as a zip under <id>/, in name order with one fixed date:
    the same files always make the same bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in pack_files(d):
            info = zipfile.ZipInfo(f"{pid}/{p.relative_to(d).as_posix()}",
                                   (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
    return buf.getvalue()


def peek(path: pathlib.Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return _read_manifest(_unpacked(path, pathlib.Path(tmp)))


def _grant_new(m: dict) -> None:
    """Keep the answer to confirm() for a plugin not loaded yet."""
    f = data_folder() / m["id"] / "settings.json"
    try:
        got = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        got = {}
    got = got if isinstance(got, dict) else {}
    got["_granted"] = permissions(m)
    if not kernel_walls():
        got["_unguarded"] = True
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(got, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(f)


def install(path: pathlib.Path, grant: bool = False) -> pathlib.Path:
    """Copy a plugin in, replacing the code of one with the same id. Its
    settings live in plugin-data/, so an update keeps them. grant: the
    person was shown its permissions and said yes."""
    with tempfile.TemporaryDirectory() as tmp:
        src = _unpacked(path, pathlib.Path(tmp))
        m = _read_manifest(src)
        dest = folder() / m["id"]
        if dest.resolve() == src.resolve():
            return dest
        folder().mkdir(parents=True, exist_ok=True)
        stage = folder() / f".{m['id']}.new"
        old = folder() / f".{m['id']}.old"
        for d in (stage, old):
            shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(src, stage, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git"))
        # Renamed aside rather than deleted, so a file Windows holds open
        # fails the swap whole instead of leaving half a plugin.
        was = _PLUGINS.get(m["id"])
        if was is not None:
            was.stop()
        try:
            if dest.exists():
                try:
                    dest.rename(old)
                except OSError as e:
                    shutil.rmtree(stage, ignore_errors=True)
                    raise OSError(f"{dest.name} is in use ({e.strerror}); quit "
                                  "Mild Lyrics and install it again") from None
            try:
                stage.rename(dest)
            except OSError:
                if old.exists():
                    old.rename(dest)
                raise
        except OSError:
            if was is not None and was.values["on"]:
                was.start()             # still its old files: carry on
            raise
        shutil.rmtree(old, ignore_errors=True)
    if was is not None:
        was.removed = False
        if grant:
            was.values["_granted"] = permissions(m)
            if not kernel_walls():
                was.values["_unguarded"] = True
            was.save()
        if not was.reload():
            was.stale = True
    elif grant:
        _grant_new(m)
    return dest


def uninstall(pid: str) -> None:
    """Stop a plugin and delete its code; its settings in plugin-data/ stay,
    so installing it again keeps them."""
    p = _PLUGINS.get(pid)
    dest, old = folder() / pid, folder() / f".{pid}.old"
    if p is not None:
        p.stop()
    shutil.rmtree(old, ignore_errors=True)
    try:
        dest.rename(old)
    except FileNotFoundError:
        pass
    except OSError as e:
        if p is not None and p.values["on"]:
            p.start()
        raise OSError(f"{pid} is in use ({e.strerror}); quit Mild Lyrics "
                      "and remove it from the plugins folder") from None
    shutil.rmtree(old, ignore_errors=True)
    if p is not None:
        p.removed = True
