"""Old karaoke pagination and offscreen painting regressions."""
import os
import pathlib
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "mild-lyrics"))
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
import renderers as RD


class OldKaraokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication(["test", "-platform", "offscreen"])

    def renderer(self, lines):
        v = types.SimpleNamespace(lines=lines, synced=True, roman="off", furigana=False,
                                  periodic="off", scroll=0.0, line_rects=[], content_h=0.0)
        v.width = lambda: 640
        v.lyric_px = lambda: 30
        v.position = lambda: 12.0
        v.track_offset = lambda: 0.0
        v.song_title = lambda: "A song"
        v.artist = lambda: "An artist"
        r = RD.OldKaraoke(v)
        r.rows_of = lambda ln, fm, width: [[(0, 50, ln.get("text", "line"),
                                           ln.get("start"), ln.get("end"))]]
        return r

    def test_registered_and_four_row_pages(self):
        self.assertIs(RD.RENDERERS["old karaoke"], RD.OldKaraoke)
        lines = [{"text": f"line {i}", "start": 10 + i * 2, "end": 12 + i * 2}
                 for i in range(9)]
        lines.append({"credits": ["provider"]})
        r = self.renderer(lines)
        pages = r.pages(r.face_pair(30)[1], 500)
        self.assertEqual([len(p[2]) for p in pages], [4, 4, 1])
        self.assertEqual([p[0] for p in pages], [7, 18, 26])
        self.assertIs(pages, r.pages(r.face_pair(30)[1], 500))

    def test_long_gaps_and_instrumentals_start_pages(self):
        lines = [{"start": 10, "end": 12}, {"start": 22, "end": 24},
                 {"dots": True, "start": 24, "end": 26}, {"start": 27, "end": 29}]
        r = self.renderer(lines)
        pages = r.pages(r.face_pair(30)[1], 500)
        self.assertEqual([[i for i, _rows in p[2]] for p in pages], [[0], [1], [3]])
        self.assertEqual(pages[1][0], 19)

    def test_replacing_document_invalidates_pages(self):
        r = self.renderer([{"text": "old", "start": 10, "end": 12}])
        fm = r.face_pair(30)[1]
        old = r.pages(fm, 500)
        r.v.lines = [{"text": "new", "start": 20, "end": 22}]
        new = r.pages(fm, 500)
        self.assertIsNot(old, new)
        self.assertEqual(new[0][0], 17)

    def test_real_wrapping_splits_a_long_line_into_timed_four_row_pages(self):
        from lyrics_gui import stamp_rows, wrap_shape
        pieces = [(10 + i, 11 + i, f"word{i} ", False) for i in range(12)]
        r = self.renderer([{"text": "a long line", "start": 10, "end": 22}])
        # Use the real shaping/wrapping/timing, not the single-row test stub.
        r.rows_of = lambda ln, fm, width: stamp_rows(wrap_shape(pieces, fm, width, "centre"), pieces)
        pages = r.pages(r.face_pair(30)[1], 55)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(sum(len(rows) for _i, rows in p[2]) <= r.ROWS for p in pages))
        shows = [show for show, _end, _rows in pages]
        self.assertTrue(all(a < b for a, b in zip(shows, shows[1:])), shows)
        self.assertAlmostEqual(pages[-1][1], 22)
        for show, end, _page in pages:
            self.assertLess(show, end)

    def test_overlapping_vocals_cannot_hide_the_next_page(self):
        lines = [{"text": f"lead {i}", "start": 10 + i, "end": 30} for i in range(4)]
        lines += [{"text": "overlapping vocal", "start": 18, "end": 26}]
        r = self.renderer(lines)
        pages = r.pages(r.face_pair(30)[1], 500)
        self.assertEqual(pages[0][1], 30)
        self.assertEqual(pages[1][:2], (18, 26))
        image = QImage(640, 400, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            r.v.position = lambda: 20
            with mock.patch.object(r, "wipe_row") as wipe:
                r.paint(painter, 20, 600, 400)
                self.assertEqual(wipe.call_args.args[2]["text"], "overlapping vocal")
        finally:
            painter.end()

    def test_wrapped_lead_and_early_adlib_are_scheduled_before_grouping(self):
        from lyrics_gui import stamp_rows, wrap_shape
        lead = {"text": "long lead", "start": 10, "end": 22}
        adlib = {"text": "adlib", "start": 12, "end": 13, "background": True}
        r = self.renderer([lead, adlib])
        pieces = [(10 + i, 11 + i, f"word{i} ", False) for i in range(12)]
        r.rows_of = lambda ln, fm, width: stamp_rows(wrap_shape(
            pieces if ln is lead else [(12, 13, "adlib", False)], fm, width, "centre"),
            pieces if ln is lead else [(12, 13, "adlib", False)])
        width = 90
        fm = r.face_pair(r.v.lyric_px() * 0.82)[1]
        pages = r.pages(fm, width)
        self.assertGreater(len(pages), 2)
        shows = [p[0] for p in pages]
        self.assertEqual(shows, sorted(shows))
        self.assertTrue(all(sum(len(rows) for _i, rows in p[2]) <= r.ROWS for p in pages))
        image = QImage(640, 400, QImage.Format.Format_ARGB32)
        painter = QPainter(image)
        try:
            # Visit the middle lead chunks in both playback and reverse seek
            # order, after the early adlib has ended. Their exact fragments,
            # not merely a page number, must actually reach the painter.
            for pos in (16.5, 19.5, 16.5):
                r.v.position = lambda pos=pos: pos
                with mock.patch.object(r, "wipe_row") as wipe:
                    r.paint(painter, 20, width / 0.92, 400)
                    fragments = [fragment for call in wipe.call_args_list
                                 for fragment in call.args[1]]
                    self.assertTrue(any(s is not None and e is not None and s <= pos < e
                                        for _x, _w, _txt, s, e in fragments), (pos, shows))
        finally:
            painter.end()

    def test_black_background_title_page_and_seek(self):
        r = self.renderer([{"text": "first", "start": 10, "end": 12},
                           {"text": "second", "start": 30, "end": 32}])
        image = QImage(640, 400, QImage.Format.Format_ARGB32)
        image.fill(0xffffffff)
        painter = QPainter(image)
        try:
            with mock.patch.object(r, "title_card") as title, mock.patch.object(r, "wipe_row") as wipe:
                r.v.position = lambda: 0
                r.paint(painter, 20, 600, 400)
                title.assert_called_once()
                self.assertEqual(image.pixelColor(0, 0).name(), "#000000")
                r.v.position = lambda: 30
                r.paint(painter, 20, 600, 400)
                self.assertEqual(wipe.call_args.args[2]["text"], "second")
                r.v.position = lambda: 10
                r.paint(painter, 20, 600, 400)
                self.assertEqual(wipe.call_args.args[2]["text"], "first")
                self.assertEqual(len(r.v.line_rects), 1)
        finally:
            painter.end()


if __name__ == "__main__":
    unittest.main()
