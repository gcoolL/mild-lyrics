"""Which interface both programs are drawn in, "new" or "classic": one switch
in a file of its own, watched by both. Anything unreadable is "new"."""
from __future__ import annotations

import json
import pathlib

CHOICES = ("new", "classic")
DEFAULT = "new"


def path() -> pathlib.Path:
    import lyrics_gui as L
    return L.app_dir("config") / "interface.json"


def get() -> str:
    try:
        got = json.loads(path().read_text(encoding="utf-8")).get("interface")
    except Exception:                                    # noqa: BLE001
        return DEFAULT
    return got if got in CHOICES else DEFAULT


def put(value: str) -> None:
    if value not in CHOICES:
        return
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"interface": value}), encoding="utf-8")
    except Exception:                                    # noqa: BLE001
        pass


def classic() -> bool:
    return get() == "classic"


class Watch:
    """Calls `then(value)` when the other program flips the switch.

    Polled rather than watched with QFileSystemWatcher: that one stops
    watching a file the moment it is replaced, which is how the file is
    written, and a two-second look at one small file costs nothing.
    """

    def __init__(self, parent, then, every_ms: int = 1500) -> None:
        from PyQt6.QtCore import QTimer
        self.then, self.was = then, get()
        self.timer = QTimer(parent)
        self.timer.timeout.connect(self._look)
        self.timer.start(every_ms)

    def seen(self, value: str) -> None:
        """This program set it itself; do not call back about it."""
        self.was = value

    def _look(self) -> None:
        now = get()
        if now != self.was:
            self.was = now
            try:
                self.then(now)
            except Exception:                            # noqa: BLE001
                import traceback
                traceback.print_exc()
