"""One plugin's own process: walls first (plugin_sandbox), then its code.

Started by plugins.Plugin with the spec as its first line on stdin; talks
to Mild Lyrics in JSON lines over its stdin/stdout. The plugin's own print()
goes to stderr, which Mild Lyrics logs under the plugin's name.
"""

import importlib.util
import json
import os
import pathlib
import queue
import select
import socket
import sys
import threading
import time
import traceback
import types

FAILS_OUT = 3
STATUS_EVERY = 0.25
MAX_LINE = 4 * 1024 * 1024


class Host:
    """The pipe to Mild Lyrics, shared by the plugin's threads."""

    def __init__(self, out) -> None:
        self._out = out
        self._lock = threading.Lock()
        self.inbox: queue.Queue = queue.Queue()
        self._replies: dict = {}
        self._next = 0

    def send(self, **msg) -> None:
        line = json.dumps(msg, default=str, separators=(",", ":")) + "\n"
        with self._lock:
            self._out.write(line.encode("utf-8"))
            self._out.flush()

    def ask(self, timeout: float = 30.0, **msg):
        with self._lock:
            self._next += 1
            rid = self._next
        got = threading.Event()
        self._replies[rid] = [got, None]
        self.send(id=rid, **msg)
        if not got.wait(timeout):
            self._replies.pop(rid, None)
            raise TimeoutError(f"Mild Lyrics did not answer {msg.get('t')}")
        return self._replies.pop(rid)[1]

    def read(self, stream) -> None:
        for raw in stream:
            if len(raw) > MAX_LINE:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("t") == "reply" and msg.get("id") in self._replies:
                slot = self._replies[msg["id"]]
                slot[1] = msg
                slot[0].set()
            else:
                self.inbox.put(msg)
        self.inbox.put({"t": "stop"})           # Mild Lyrics went away


class Bridge:
    """The way out of the plugin's own network namespace: a listener on its
    loopback for the plugin's HTTPS_PROXY, and for each connection a fresh
    one to Mild Lyrics' proxy, made outside and handed in over `ctl`."""

    def __init__(self, ctl: socket.socket) -> None:
        self.ctl = ctl
        self.lock = threading.Lock()
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.port = self.srv.getsockname()[1]

    def start(self) -> None:
        threading.Thread(target=self._serve, daemon=True, name="bridge").start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        try:
            with self.lock:
                self.ctl.sendall(b"c")
                _msg, fds, _f, _a = socket.recv_fds(self.ctl, 1, 1)
        except OSError:
            fds = []
        if not fds:
            conn.close()
            return
        up = fds[0]                     # a raw fd: a socket made outside
        try:
            while True:
                ready, _, _ = select.select([conn, up], [], [], 120)
                if not ready:
                    return
                if conn in ready:
                    data = conn.recv(65536)
                    if not data:
                        return
                    os.write(up, data)
                if up in ready:
                    data = os.read(up, 65536)
                    if not data:
                        return
                    conn.sendall(data)
        except OSError:
            return
        finally:
            conn.close()
            os.close(up)


class Api:
    """What start(api) is handed: the same calls as before plugins had their
    own process; see docs/plugins/README.md."""

    def __init__(self, run: "Runner") -> None:
        self._r = run
        spec = run.spec
        self.id = spec["id"]
        self.version = spec["api_version"]
        self.folder = pathlib.Path(spec["dir"])
        self.data_folder = pathlib.Path(spec["data"])

    def get(self, key):
        return self._r.values[key]

    def __getitem__(self, key):
        return self._r.values[key]

    def set(self, key, value) -> None:
        if key not in self._r.values:
            raise KeyError(key)
        self._r.host.send(t="set", key=key, value=value)

    def reset(self) -> None:
        self._r.host.send(t="reset")

    def every(self, seconds, fn) -> None:
        self._r.ticks.append([max(0.1, float(seconds)), fn, 0.0])
        self._r.want("playback")

    def playback(self) -> dict:
        self._r.want("playback")
        return dict(self._r.playback)

    def status(self, fn) -> None:
        self._r.status_fn = fn

    def on_change(self, fn) -> None:
        self._r.changed.append(fn)

    def on_action(self, key, fn) -> None:
        self._r.actions[key] = fn

    def lyrics(self):
        self._r.want("lyrics")
        return self._r.lyrics

    def control(self, name, value=None) -> None:
        if not self._r.spec["perms"].get("player"):
            raise PermissionError("this plugin did not ask to control the player")
        self._r.host.send(t="control", name=name, value=value)

    def spotify(self, expression: str):
        if not self._r.spec["perms"].get("spotify"):
            raise PermissionError("this plugin did not ask to run scripts in Spotify")
        got = self._r.host.ask(t="spotify", js=str(expression))
        if got.get("ok"):
            return got.get("value")
        kind = {"connection": ConnectionError, "script": RuntimeError}.get(
            got.get("kind"), RuntimeError)
        raise kind(got.get("error") or "Spotify did not answer")

    def listener(self) -> socket.socket:
        """A listening TCP socket on 127.0.0.1 for other apps on this computer
        to connect to (API 3; needs the listen permission). One per process."""
        if not self._r.spec["perms"].get("listen"):
            raise PermissionError("this plugin did not ask to accept connections")
        if self._r.listener is None:
            self._r.listener = socket.create_server(("127.0.0.1", 0))
        return self._r.listener

    def toast(self, text) -> None:
        self._r.host.send(t="toast", text=str(text)[:300])

    def log(self, *bits) -> None:
        self._r.host.send(t="log", text=" ".join(str(b) for b in bits)[:2000])


class Runner:
    def __init__(self, spec: dict, host: Host) -> None:
        self.spec, self.host = spec, host
        self.values = dict(spec["values"])
        self.ticks: list = []
        self.changed: list = []
        self.actions: dict = {}
        self.status_fn = None
        self.listener = None            # a socket Mild Lyrics opened for it
        self.playback: dict = {}
        self.lyrics = None
        self.fails: dict = {}
        self._wanted: set = set()
        self._said = None
        self._status_at = 0.0

    def want(self, what: str) -> None:
        if what not in self._wanted:
            self._wanted.add(what)
            self.host.send(t="want", what=what)

    def call(self, fn, *a):
        try:
            got = fn(*a)
        except Exception as e:                           # noqa: BLE001
            self.fails[fn] = self.fails.get(fn, 0) + 1
            self.host.send(t="log", text="raised:\n" + traceback.format_exc().rstrip())
            if self.fails[fn] >= FAILS_OUT:
                self.host.send(t="failed", why=f"{type(e).__name__}: {e}")
                os._exit(1)
            return None
        self.fails.pop(fn, None)
        return got

    def status(self, now: float) -> None:
        if self.status_fn is None or now - self._status_at < STATUS_EVERY:
            return
        self._status_at = now
        text = self.call(self.status_fn)
        text = str(text)[:200] if text else ""
        if text != self._said:
            self._said = text
            self.host.send(t="status", text=text)

    def loop(self, module) -> None:
        while True:
            try:
                msg = self.host.inbox.get(timeout=0.05)
            except queue.Empty:
                msg = None
            if msg is not None:
                t = msg.get("t")
                if t == "stop":
                    stop = getattr(module, "stop", None)
                    if stop is not None:
                        self.call(stop)
                    return
                if t == "playback":
                    self.playback = msg.get("data") or {}
                elif t == "lyrics":
                    self.lyrics = msg.get("data")
                elif t == "changed":
                    self.values[msg["key"]] = msg["value"]
                    for fn in list(self.changed):
                        self.call(fn, msg["key"], msg["value"])
                elif t == "action":
                    fn = self.actions.get(msg.get("key"))
                    if fn is not None:
                        self.call(fn)
            now = time.monotonic()
            for tk in list(self.ticks):
                if now >= tk[2]:
                    tk[2] = now + tk[0]
                    self.call(tk[1], dict(self.playback))
            self.status(now)


def _walls(spec: dict, run: "Runner"):
    """Put the sandbox up. (level, net, bridge): level 'kernel' or 'guards';
    net 'namespace' (no route out but the bridge), 'ports' (the kernel limits
    TCP to the proxy's port) or 'guards'."""
    import plugin_sandbox as SB
    w = spec["walls"]
    SB.die_with_parent()
    SB.limits()
    # Sockets Mild Lyrics opened for it, taken up before the guards, which
    # refuse making a socket of anything but TCP.
    ctl = socket.socket(fileno=w["bridge_fd"]) if w.get("bridge_fd") is not None else None
    if w.get("listener_fd") is not None:
        run.listener = socket.socket(fileno=w["listener_fd"])
    level, net, bridge, port = "guards", "guards", None, w["proxy_port"]
    if spec["kernel"]:
        if ctl is not None and SB.netns():          # single-threaded still
            bridge = Bridge(ctl)
            port, net = bridge.port, "namespace"
            url = os.environ.get("HTTPS_PROXY", "")
            for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
                if k in os.environ:
                    os.environ[k] = url.rsplit(":", 1)[0] + f":{port}"
        elif ctl is not None:
            ctl.close()
        # A plugin made before api.listener() binds its own socket: outside a
        # namespace that still reaches other apps, so port 0 stays allowed
        # (the guard keeps it to loopback), as in 1.1.5.
        bind = [0] if w["listen"] and bridge is None else []
        if SB.landlock(w["read"], w["write"], [port] if port else [], bind) >= 1:
            level = "kernel"
            net = "namespace" if bridge else "ports"
        SB.seccomp()
    SB.guards(w["read"], w["write"], spec["dir"], port, w["listen"])
    for name in [n for n in sys.modules if n == "ctypes" or n.startswith(("ctypes.", "_ctypes"))]:
        del sys.modules[name]
    return level, net, bridge


def main() -> None:
    raw_in, raw_out = sys.stdin.buffer, sys.stdout.buffer
    spec = json.loads(raw_in.readline())
    sys.path[:] = spec["path"]
    sys.stdout = sys.stderr                     # the plugin's print() is a log line
    host = Host(raw_out)
    os.chdir(spec["data"])
    run = Runner(spec, host)
    level, net, bridge = _walls(spec, run)
    if bridge is not None:
        bridge.start()
    host.send(t="ready", level=level, net=net)
    threading.Thread(target=host.read, args=(raw_in,), daemon=True).start()
    if "mild_plugins" not in sys.modules:
        pkg = types.ModuleType("mild_plugins")
        pkg.__path__ = []
        sys.modules["mild_plugins"] = pkg
    lib = os.path.join(spec["dir"], "lib")
    if os.path.isdir(lib):
        sys.path.append(lib)
    name = "mild_plugins." + spec["id"].replace("-", "_")
    try:
        loc = importlib.util.spec_from_file_location(
            name, os.path.join(spec["dir"], "__init__.py"),
            submodule_search_locations=[spec["dir"]])
        module = importlib.util.module_from_spec(loc)
        sys.modules[name] = module
        loc.loader.exec_module(module)
        start = getattr(module, "start", None)
        if start is None:
            raise AttributeError("the plugin has no start(api)")
        start(Api(run))
    except Exception as e:                               # noqa: BLE001
        host.send(t="log", text="could not start:\n" + traceback.format_exc().rstrip())
        host.send(t="failed", why=f"{type(e).__name__}: {e}")
        os._exit(1)
    host.send(t="started")
    run.loop(module)
    os._exit(0)


if __name__ == "__main__":
    main()
