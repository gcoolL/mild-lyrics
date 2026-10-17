"""An animated cover read off disk a few frames ahead of the clock, for Memory
use "low": ~3 decoded frames instead of all of them (70-280MB), for ~1.8ms of
a worker thread per frame. Looks like the frame list it replaces."""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap

AHEAD = 3


def decode(path: str, cap: int) -> QImage | None:
    """One frame, no wider than cap. QImage only: safe off the GUI thread."""
    img = QImage()
    if not img.load(str(path)) or img.isNull():
        return None
    if img.width() > cap:
        img = img.scaledToWidth(cap, Qt.TransformationMode.SmoothTransformation)
    return img


class _State:
    """What the decode thread shares with the stream; the thread never holds
    the stream itself, so dropping the stream is what stops it."""

    def __init__(self, paths: list, cap: int) -> None:
        self.paths, self.cap = paths, cap
        self.ready: dict[int, QImage] = {}
        self.want = 0
        self.stop = False
        self.cv = threading.Condition()

    def todo(self) -> int | None:
        n = len(self.paths)
        for d in range(AHEAD + 1):
            i = (self.want + d) % n
            if i not in self.ready:
                return i
        return None

    def run(self) -> None:
        while True:
            with self.cv:
                while not self.stop and self.todo() is None:
                    self.cv.wait(0.5)
                if self.stop:
                    return
                i = self.todo()
            img = decode(self.paths[i], self.cap)
            with self.cv:                   # unreadable: null, the last frame holds
                self.ready[i] = img if img is not None else QImage()


class MotionStream:
    """Frames by index, as `motion_frames[i % len(motion_frames)]` reads them;
    None until the first one is decoded. Index it on the GUI thread only."""
    step = 1

    def __init__(self, paths, cap: int, middle: QImage | None = None) -> None:
        self._s = _State(list(paths), cap)
        self.middle = middle
        self._shown: tuple[int, QPixmap | None] = (-1, None)
        self._thread: threading.Thread | None = None

    def __len__(self) -> int:
        return len(self._s.paths)

    def __bool__(self) -> bool:
        return bool(self._s.paths)

    def __iter__(self):
        raise TypeError("a MotionStream is read by index, a frame at a time")

    def __getitem__(self, i: int) -> QPixmap | None:
        s = self._s
        n = len(s.paths)
        i %= n
        if self._shown[0] == i:
            return self._shown[1]
        with s.cv:
            img = s.ready.get(i)
            s.want = i
            for k in [k for k in s.ready if (k - i) % n > AHEAD]:
                del s.ready[k]
            s.cv.notify()
        if self._thread is None:
            self._thread = threading.Thread(target=s.run, daemon=True,
                                            name="motion-stream")
            self._thread.start()
        if img is not None and not img.isNull():
            self._shown = (i, QPixmap.fromImage(img))
        return self._shown[1]

    def close(self) -> None:
        with self._s.cv:
            self._s.stop = True
            self._s.cv.notify()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:                                # noqa: BLE001
            pass
