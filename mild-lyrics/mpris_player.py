"""Mild Lyrics' own player on the session bus (MPRIS) as
org.mpris.MediaPlayer2.mild_lyrics, while the local player has a queue.
Linux only. Notes: docs/notes/mild-lyrics/home_page.md."""
from __future__ import annotations

import sys
import time

NAME = "org.mpris.MediaPlayer2.mild_lyrics"
EDITOR_NAME = "org.mpris.MediaPlayer2.ttml_editor"     # the TTML Editor timing a file (editor/mpris.py)
OWN = (NAME, EDITOR_NAME)                              # never followed as somebody else's player
PATH = "/org/mpris/MediaPlayer2"
ROOT = "org.mpris.MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
PROPS = "org.freedesktop.DBus.Properties"
LOOP = {"off": "None", "one": "Track", "all": "Playlist"}

try:
    if not sys.platform.startswith("linux"):
        raise ImportError("not Linux")
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
except Exception:                                            # noqa: BLE001
    dbus = None


def available() -> bool:
    return dbus is not None


if dbus is not None:
    class _Player(dbus.service.Object):
        """The two MPRIS interfaces, answered from the local player."""

        def __init__(self, bus, owner) -> None:
            super().__init__(bus, PATH)
            self.o = owner

        # --------------------------------------------------- properties
        def _root(self) -> dict:
            return {"CanQuit": False, "CanRaise": True, "HasTrackList": False,
                    "Identity": self.o.identity, "DesktopEntry": self.o.desktop,
                    "SupportedUriSchemes": dbus.Array([], signature="s"),
                    "SupportedMimeTypes": dbus.Array([], signature="s")}

        def _player(self) -> dict:
            pl = self.o.player
            has = bool(pl.queue)
            rate = self.o.rate()
            return {"PlaybackStatus": self.o.status(),
                    "LoopStatus": LOOP.get(pl.repeat, "None"),
                    "Rate": rate, "MinimumRate": min(1.0, rate), "MaximumRate": max(1.0, rate),
                    "Shuffle": bool(pl.shuffle),
                    "Metadata": self.o.metadata(),
                    "Volume": float(pl.volume),
                    "Position": dbus.Int64(int(self.o.position() * 1e6)),
                    "CanGoNext": has and self.o.skips, "CanGoPrevious": has and self.o.skips,
                    "CanPlay": has, "CanPause": has,
                    "CanSeek": has, "CanControl": True}

        @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
        def Get(self, iface, prop):                          # noqa: N802
            return self.GetAll(iface)[prop]

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, iface):                             # noqa: N802
            if iface == ROOT:
                return self._root()
            if iface == PLAYER:
                return self._player()
            return {}

        @dbus.service.method(PROPS, in_signature="ssv")
        def Set(self, iface, prop, value):                   # noqa: N802
            pl = self.o.player
            if iface != PLAYER:
                return
            if prop == "Volume":
                pl.set_volume(float(value))
            elif prop == "Shuffle":
                self.o.set_shuffle(bool(value))
            elif prop == "LoopStatus":
                self.o.set_repeat({v: k for k, v in LOOP.items()}.get(str(value), "off"))
            self.o.changed()

        @dbus.service.signal(PROPS, signature="sa{sv}as")
        def PropertiesChanged(self, iface, changed, invalidated):   # noqa: N802
            pass

        @dbus.service.signal(PLAYER, signature="x")
        def Seeked(self, position):                          # noqa: N802
            pass

        # ------------------------------------------------------ methods
        @dbus.service.method(ROOT)
        def Raise(self):                                     # noqa: N802
            self.o.raise_window()

        @dbus.service.method(ROOT)
        def Quit(self):                                      # noqa: N802
            pass

        @dbus.service.method(PLAYER)
        def Next(self):                                      # noqa: N802
            self.o.command("Next")

        @dbus.service.method(PLAYER)
        def Previous(self):                                  # noqa: N802
            self.o.command("Previous")

        @dbus.service.method(PLAYER)
        def PlayPause(self):                                 # noqa: N802
            self.o.command("PlayPause")

        @dbus.service.method(PLAYER)
        def Play(self):                                      # noqa: N802
            if self.o.status() != "Playing":
                self.o.command("PlayPause")

        @dbus.service.method(PLAYER)
        def Pause(self):                                     # noqa: N802
            if self.o.status() == "Playing":
                self.o.command("PlayPause")

        @dbus.service.method(PLAYER)
        def Stop(self):                                      # noqa: N802
            self.Pause()

        @dbus.service.method(PLAYER, in_signature="x")
        def Seek(self, offset):                              # noqa: N802
            self.o.seek(self.o.position() + offset / 1e6)

        @dbus.service.method(PLAYER, in_signature="ox")
        def SetPosition(self, track, position):              # noqa: N802
            if str(track) == self.o.track_path():
                self.o.seek(position / 1e6)

        @dbus.service.method(PLAYER, in_signature="s")
        def OpenUri(self, uri):                              # noqa: N802
            pass


class Mpris:
    """Publishes the local player as "Mild Lyrics" while it has a queue (or, through an
    adapter with the same few methods, the TTML Editor while it times a file)."""

    def __init__(self, player, raise_window, name: str = NAME, identity: str = "Mild Lyrics",
                 desktop: str = "mild-lyrics", skips: bool = True) -> None:
        self.player = player
        self.raise_window = raise_window
        self.bus_name, self.identity, self.desktop, self.skips = name, identity, desktop, skips
        self._was = None                 # (position, monotonic, rate if playing else 0) at the last changed()
        self.bus = None
        self.obj = None
        self.name = None
        self._last: dict = {}
        self._n = 0
        self._tid = None
        if not available():
            return
        try:
            self.bus = dbus.SessionBus(private=True, mainloop=DBusGMainLoop())
        except Exception:                                    # noqa: BLE001
            self.bus = None

    # ------------------------------------------------------- from the player
    def status(self) -> str:
        pl = self.player
        if not pl.queue:
            return "Stopped"
        return "Playing" if pl.playing() else "Paused"

    def position(self) -> float:
        return float(self.player.reading()["pos"]) if self.player.queue else 0.0

    def rate(self) -> float:
        got = getattr(self.player, "rate", None)
        try:
            return float(got()) if callable(got) else 1.0
        except Exception:                                    # noqa: BLE001
            return 1.0

    def track_path(self) -> str:
        return f"/org/{self.bus_name.rsplit('.', 1)[-1]}/track/{self._n}"

    def metadata(self) -> dict:
        t = self.player.current or {}
        r = self.player.reading() if self.player.queue else {"meta": {}}
        length = float((r.get("meta") or {}).get("length") or (t.get("ms") or 0) / 1000.0)
        md = {"mpris:trackid": dbus.ObjectPath(self.track_path()),
              "mpris:length": dbus.Int64(int(length * 1e6)),
              "xesam:title": t.get("title", ""),
              "xesam:artist": dbus.Array([a.strip() for a in (t.get("artist") or "").split(",") if a.strip()]
                                         or [""], signature="s"),
              "xesam:album": t.get("album", "")}
        art = t.get("art") or ""
        if art:
            md["mpris:artUrl"] = art
        return dbus.Dictionary(md, signature="sv")

    def command(self, what: str) -> None:
        self.player.tell(what)

    def seek(self, to: float) -> None:
        self.player.tell("seek", max(0.0, to))
        if self.obj is not None:
            self.obj.Seeked(dbus.Int64(int(max(0.0, to) * 1e6)))
            if self._was is not None:              # said already: not again as an in-app jump
                self._was = (max(0.0, to), time.monotonic(), self._was[2])

    def set_shuffle(self, on: bool) -> None:
        self.player.shuffle = on

    def set_repeat(self, mode: str) -> None:
        self.player.repeat = mode

    # ------------------------------------------------------------ on the bus
    def changed(self) -> None:
        """The player changed: get on the bus or off it, and say what changed."""
        if self.bus is None:
            return
        want = bool(self.player.queue)
        if want and self.obj is None:
            try:
                self.name = dbus.service.BusName(self.bus_name, self.bus, do_not_queue=True)
                self.obj = _Player(self.bus, self)
            except Exception:                                # noqa: BLE001
                self.name = self.obj = None
                return
        if not want:
            if self.obj is not None:
                try:
                    self.obj.remove_from_connection()
                except Exception:                            # noqa: BLE001
                    pass
                self.obj = self.name = None
                self._last, self._was = {}, None
            return
        cur = self.player.current or {}
        key = (cur.get("title"), cur.get("artist"), id(cur))
        if key != self._tid:
            self._tid = key
            self._n += 1
        now = self.obj._player()
        pos = int(now.pop("Position", 0)) / 1e6
        diff = {k: v for k, v in now.items() if self._last.get(k) != v}
        self._last = now
        if diff:
            self.obj.PropertiesChanged(PLAYER, dbus.Dictionary(diff, signature="sv"),
                                       dbus.Array([], signature="s"))
        # A jump made inside the app (a click on a line) is a seek to the widgets too.
        t = time.monotonic()
        if self._was is not None:
            p0, t0, r0 = self._was
            if abs(pos - (p0 + (t - t0) * r0)) > 0.75:
                self.obj.Seeked(dbus.Int64(int(pos * 1e6)))
        self._was = (pos, t, self.rate() if now.get("PlaybackStatus") == "Playing" else 0.0)

    def close(self) -> None:
        if self.obj is not None:
            try:
                self.obj.remove_from_connection()
            except Exception:                                # noqa: BLE001
                pass
        self.obj = self.name = None
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:                                # noqa: BLE001
                pass
            self.bus = None
