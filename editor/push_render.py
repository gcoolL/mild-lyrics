"""The live push's TTML rendered off the GUI thread, for long songs: only
the newest asked-for snapshot is rendered; `ready` brings it back."""
from __future__ import annotations

import threading
import traceback

from PyQt6.QtCore import QObject, pyqtSignal

from . import model as M

# Below this many lines the push renders in place, as it always did.
LONG = 400


class Renderer(QObject):
    ready = pyqtSignal(int, int, str)       # ask number, timed lines, TTML

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cv = threading.Condition()
        self._want = None
        self._thread: threading.Thread | None = None

    def ask(self, n: int, snap: M.Doc) -> None:
        """Render `snap` (a model.snapshot, never edited) as push number `n`;
        one still waiting is dropped."""
        with self._cv:
            self._want = (n, snap)
            self._cv.notify()
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="editor-push-render")
            self._thread.start()

    def _loop(self) -> None:
        while True:
            with self._cv:
                while self._want is None:
                    self._cv.wait()
                n, snap = self._want
                self._want = None
            try:
                shown = M.timed_only(snap)
                text = M.to_ttml(shown) if shown.lines else ""
                self.ready.emit(n, len(shown.lines), text)
            except Exception:                           # noqa: BLE001
                traceback.print_exc()
