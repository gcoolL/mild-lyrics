"""Lay out fetched-ahead songs before they start, a slice at a time, so the
first paint of a new song finds its measurements already made. See
docs/notes/mild-lyrics/layout_ahead.md."""
from __future__ import annotations

import time
from collections import OrderedDict

from PyQt6.QtCore import QTimer

import spicy_lyrics as SL

SLICE_S = 0.0006    # work per turn; one long line can overrun it, once
GAP_MS = 30         # between turns
KEEP = 16           # songs remembered as done


class _Job:
    def __init__(self, tid: str, raw: list) -> None:
        self.tid, self.raw = tid, raw
        self.lines = None
        self.japanese = False
        self.cache: dict = {}
        self.i = 0
        self.width = 0.0


class LayoutAhead:
    """Fed by Fetcher.ahead_ready; works on the window's main thread."""

    def __init__(self, view) -> None:
        self.v = view
        self.jobs: list[_Job] = []
        self.done: OrderedDict = OrderedDict()
        self.timer = QTimer()
        self.timer.setInterval(GAP_MS)
        self.timer.timeout.connect(self.step)

    def key(self) -> tuple:
        """What a layout depends on besides the words."""
        v = self.v
        return (int(v._lyr_width()), int(v.lyric_px()), v.align, v.roman,
                v.furigana, v.lyric_font_key())

    def want(self, tid: str, raw) -> None:
        if not tid or not raw or tid == self.v.clock.tid:
            return
        if self.done.get(tid) == self.key():
            return
        self.jobs = [j for j in self.jobs if j.tid != tid]
        self.jobs.append(_Job(tid, list(raw)))
        if not self.timer.isActive():
            self.timer.start()

    def step(self) -> None:
        v = self.v
        end = time.perf_counter() + SLICE_S
        while self.jobs and time.perf_counter() < end:
            job = self.jobs[0]
            if job.tid == v.clock.tid or v.instrumental():
                # Playing already (its own first paint did the work), or the
                # column is not its usual width: nothing to warm against.
                self.jobs.pop(0)
                continue
            try:
                if job.lines is None:
                    job.lines = v.build_lines(job.raw)
                    job.japanese = any(SL.KANA.search(ln.get("text") or "")
                                       for ln in job.lines)
                    job.width = v._lyr_width()
                elif job.i < len(job.lines):
                    self.lay(job, job.i)
                    job.i += 1
                else:
                    self.finish(job)
            except Exception:                           # noqa: BLE001
                self.jobs.pop(0)                        # a warm-up, not a duty
        if not self.jobs:
            self.timer.stop()

    def lay(self, job: _Job, i: int) -> None:
        """The window's layout_line on one of the job's lines, with the
        job's lines and a scratch cache standing in for the song's."""
        v = self.v
        held = v.lines, v.japanese, v.layout_cache
        v.lines, v.japanese, v.layout_cache = job.lines, job.japanese, job.cache
        try:
            v.layout_line(i, job.width)
        finally:
            v.lines, v.japanese, v.layout_cache = held

    def finish(self, job: _Job) -> None:
        self.jobs.pop(0)
        self.done[job.tid] = self.key()
        self.done.move_to_end(job.tid)
        while len(self.done) > KEEP:
            self.done.popitem(last=False)
