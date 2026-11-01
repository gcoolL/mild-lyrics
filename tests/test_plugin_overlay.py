"""Overlay security, resource and timing regressions. Uses offscreen Qt;
run with python -m unittest discover -s tests."""

import concurrent.futures
import os
import pathlib
import queue
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "mild-lyrics"))
import plugins as PL
import plugin_image_paths as IP

try:
    from PyQt6.QtGui import QGuiApplication, QImage, QPainter
    import plugin_overlay as PO
    HAS_QT = True
except ImportError:
    HAS_QT = False


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.p = mock.Mock(dir=self.root, _file=self.root / "data" / "settings.json")

    def test_bad_numeric_values(self):
        for key in ("size", "margin", "bpm", "fallback_bpm", "opacity", "offset", "beats", "speed"):
            for value in (10**400, float("nan"), float("inf"), -float("inf"), [], {}):
                with self.subTest(key=key, value=type(value).__name__):
                    with self.assertRaises(ValueError):
                        PL.overlay_spec(self.p, {"image": "x.gif", key: value})

    def test_paths_do_not_touch_filesystem_on_gui(self):
        with mock.patch("os.path.realpath", side_effect=AssertionError("must not resolve")), \
                mock.patch.object(pathlib.Path, "stat", side_effect=AssertionError("must not stat")):
            self.assertIsNotNone(PL.overlay_spec(self.p, {"image": "assets/ok.gif"}))
            for path in ("../x.gif", "x\0.gif", str(self.root.parent / "outside.gif")):
                with self.assertRaises(ValueError):
                    PL.overlay_spec(self.p, {"image": path})
            if os.name == "nt":
                for path in (r"\\evil\share\x.gif", r"\\?\C:\x.gif", r"C:x.gif",
                             r"\x.gif", "CON.gif", "x.gif:stream", "x. "):
                    with self.subTest(path=path), self.assertRaises(ValueError):
                        PL.overlay_spec(self.p, {"image": path})

    def test_ipc_boundary_contains_bad_values(self):
        p = PL.Plugin(self.root, {"id": "test", "api": 4})
        for value in (10**400, float("nan"), float("inf")):
            p._handle({"t": "overlay", "data": {"image": "x.gif", "size": value}})
            self.assertIsNone(p.overlay)

    def test_spotify_reply_cannot_cross_runner_generation(self):
        for error in (None, ConnectionError("disconnected"), RuntimeError("script failed")):
            with self.subTest(error=error):
                p = PL.Plugin(self.root, {"id": "test", "api": 4})
                p.running, p.proc, p._out = True, object(), queue.Queue()
                old = p._out

                def lookup(js):
                    # The original lookup is in flight while the GUI disables
                    # and enables this Plugin with a fresh process and queue.
                    p.running = False
                    p.proc, p._out = object(), queue.Queue()
                    p.running = True
                    if error:
                        raise error
                    return {"tempo": 60}

                with mock.patch.object(PL, "_spotify", lookup), \
                        mock.patch.object(PL._pool, "submit", side_effect=lambda run: run()):
                    p._spotify({"id": 1, "js": "old track"}, {"spotify": True})
                self.assertTrue(p._out.empty(), "old reply reached new runner with id 1")
                self.assertTrue(old.empty())
                # New runner reuses request id 1; only its own result arrives.
                with mock.patch.object(PL, "_spotify", return_value={"tempo": 140}), \
                        mock.patch.object(PL._pool, "submit", side_effect=lambda run: run()):
                    p._spotify({"id": 1, "js": "new track"}, {"spotify": True})
                reply = p._out.get_nowait()
                self.assertEqual(reply, {"t": "reply", "id": 1, "ok": True,
                                         "value": {"tempo": 140}})

    def test_spotify_queued_job_dropped_after_reenable(self):
        p = PL.Plugin(self.root, {"id": "test", "api": 4})
        p.running, p.proc, p._out = True, object(), queue.Queue()
        jobs = []
        with mock.patch.object(PL._pool, "submit", side_effect=jobs.append):
            p._spotify({"id": 1, "js": "old track"}, {"spotify": True})
        p.proc, p._out = object(), queue.Queue()
        with mock.patch.object(PL, "_spotify") as lookup:
            jobs[0]()
            lookup.assert_not_called()
        self.assertTrue(p._out.empty())

    def test_snapshot_regular_file_and_limits(self):
        f = self.root / "ok.bin"
        f.write_bytes(b"bounded snapshot")
        self.assertEqual(IP.snapshot(f, self.root), b"bounded snapshot")
        with mock.patch.object(IP, "MAX_INPUT", 3), self.assertRaises(ValueError):
            IP.snapshot(f, self.root)
        with self.assertRaises((OSError, ValueError)):
            IP.snapshot(self.root, self.root)
        with self.assertRaises(ValueError):
            IP.snapshot(self.root.parent / "nope", self.root)

    def test_symlink_refused(self):
        target = self.root / "real"
        target.write_bytes(b"secret")
        link = self.root / "link"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        with self.assertRaises((OSError, ValueError)):
            IP.snapshot(link, self.root)

    @unittest.skipUnless(os.name == "nt", "Windows junction check")
    def test_junction_refused(self):
        target = self.root / "real-dir"
        target.mkdir()
        (target / "x.gif").write_bytes(b"data")
        junction = self.root / "junction"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                       check=True, capture_output=True)
        self.addCleanup(lambda: os.rmdir(junction) if junction.exists() else None)
        with self.assertRaises(ValueError):
            IP.snapshot(junction / "x.gif", self.root)


@unittest.skipUnless(HAS_QT, "needs PyQt6")
class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication(["test", "-platform", "offscreen"])

    def setUp(self):
        PO.sync([])
        # Jobs from a prior test must finish before clearing test state.
        for future in list(PO._pending.values()):
            try:
                future.result(timeout=10)
            except Exception:
                pass
        PO.sync([])
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        f = self.root / "frame.png"
        im = QImage(4, 4, QImage.Format.Format_RGBA8888)
        im.fill(0xffffffff)
        self.assertTrue(im.save(str(f)))
        self.spec = {"root": str(self.root), "image": str(f), "size": 64}

    def tearDown(self):
        PO.sync([])

    def test_decoder_subprocess_roundtrip(self):
        images, delays = PO._decode(self.spec)
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].width(), 4)
        self.assertEqual(delays, [1.0])

    def test_rejects_large_dimensions_before_decode(self):
        # Valid GIF header and logical screen size over the allowed dimension.
        f = self.root / "huge.gif"
        f.write_bytes(b"GIF89a" + struct.pack("<HH", 65535, 65535)
                      + b"\x80\0\0\0\0\0\xff\xff\xff;" )
        with self.assertRaises(ValueError):
            PO._decode(dict(self.spec, image=str(f)))

    def gif(self, width, height, count):
        header = b"GIF89a" + struct.pack("<HH", width, height) + b"\x80\0\0\0\0\0\xff\xff\xff"
        frame = (b"\x21\xf9\x04\0\x02\0\0\0\x2c\0\0\0\0"
                 + struct.pack("<HH", width, height) + b"\0\x02\x02\x44\x01\0")
        f = self.root / "animation.gif"
        f.write_bytes(header + frame * count + b";")
        return dict(self.spec, image=str(f))

    def test_real_animated_gif_and_frame_limit(self):
        images, delays = PO._decode(self.gif(1, 1, 2))
        self.assertEqual(len(images), 2)
        self.assertEqual(delays, [0.02, 0.02])
        with self.assertRaisesRegex(ValueError, "frame or decoded-byte limit"):
            PO._decode(self.gif(1, 1, 257))

    def test_aggregate_pixels_rejected_from_header(self):
        with self.assertRaisesRegex(ValueError, "frame or decoded-byte limit"):
            PO._decode(self.gif(1024, 1024, 3))

    def test_decoder_timeout_kills_child(self):
        child = mock.Mock()
        child.communicate.side_effect = [subprocess.TimeoutExpired("decode", 5), (b"", b"")]
        context = mock.MagicMock()
        context.__enter__.return_value = child
        with mock.patch.object(PO.subprocess, "Popen", return_value=context):
            with self.assertRaisesRegex(ValueError, "timed out"):
                PO._decode(self.spec)
        child.kill.assert_called_once()
        self.assertEqual(child.communicate.call_count, 2)

    def test_paint_never_decodes_or_reads(self):
        image = QImage(640, 480, QImage.Format.Format_RGBA8888)
        p = QPainter(image)
        try:
            with mock.patch.object(PO, "_decode", side_effect=AssertionError("decode on GUI")), \
                    mock.patch.object(PO, "snapshot", side_effect=AssertionError("file read on GUI")):
                PO.paint(p, 640, 480, [self.spec], 0.0, [], 0.0)
        finally:
            p.end()

    def test_async_decode_and_inactive_release(self):
        PO.sync([self.spec])
        future = PO._pending[PO.image_key(self.spec)]
        future.result(timeout=10)
        PO.sync([self.spec])
        self.assertIn(PO.image_key(self.spec), PO._decoded)
        im = PO._decoded[PO.image_key(self.spec)][0][0]
        PO._pixmap(self.spec, im, 0, 64, 64, 1.0)
        self.assertTrue(PO._scaled)
        PO.sync([])
        self.assertEqual(PO._decoded_bytes(), 0)
        self.assertEqual(PO._scaled_bytes(), 0)
        self.assertFalse(PO._failed)

    def test_decoded_budget_and_no_retry_churn(self):
        images, delays = PO._decode(self.spec)
        future = concurrent.futures.Future()
        future.set_result((images, delays))
        key = PO.image_key(self.spec)
        PO._pending[key] = future
        with mock.patch.object(PO, "DECODED_BUDGET", 1), mock.patch.object(PO._pool, "submit") as submit:
            PO.sync([self.spec])
            self.assertIn(key, PO._failed)
            self.assertEqual(PO._decoded_bytes(), 0)
            for _ in range(10):
                PO.sync([self.spec])
            submit.assert_not_called()

    def test_scaled_budget_single_frames_dpr_and_filter(self):
        im = QImage(4, 4, QImage.Format.Format_RGBA8888)
        for index in range(20):
            PO._pixmap(self.spec, im, index, 1024, 1024, 1.0)
            self.assertLessEqual(PO._scaled_bytes(), PO.SCALED_BUDGET)
        self.assertLess(len(PO._scaled), 20)
        PO._pixmap(self.spec, im, 1, 32, 32, 2.0)
        PO._pixmap(dict(self.spec, pixelated=True), im, 1, 32, 32, 2.0)
        self.assertEqual(len([key for key in PO._scaled if key[1] == 1 and key[2] == 32]), 2)
        PO._pixmap(self.spec, im, 0, 10**6, 10**6, 1.0)
        self.assertLessEqual(PO._scaled_bytes(), PO.SCALED_BUDGET)

    def test_active_cap_and_pending_work_bounded(self):
        specs = [dict(self.spec, epoch=i) for i in range(30)]
        with mock.patch.object(PO._pool, "submit", side_effect=lambda *a: concurrent.futures.Future()) as submit:
            for _ in range(10):
                PO.sync(specs)
            self.assertEqual(len(PO._active), PO.MAX_ACTIVE)
            self.assertEqual(len(PO._pending), 2)
            self.assertEqual(submit.call_count, 2)
        PO.sync([])

    def test_large_static_overlays_do_not_rescale_on_every_paint(self):
        image = QImage(1024, 1024, QImage.Format.Format_RGBA8888)
        image.fill(0xffffffff)
        counted = mock.Mock(wraps=image)
        counted.width.return_value = counted.height.return_value = 1024
        specs = [dict(self.spec, epoch=i, size=2048) for i in range(PO.MAX_ACTIVE)]
        for s in specs:
            PO._decoded[PO.image_key(s)] = ([counted], [1.0])
        target = QImage(3840, 2160, QImage.Format.Format_RGBA8888)
        painter = QPainter(target)
        try:
            PO.paint(painter, 3840, 2160, specs, 0, [], 0)
            self.assertEqual(counted.scaled.call_count, PO.MAX_ACTIVE)
            for _ in range(3):
                PO.paint(painter, 3840, 2160, specs, 0, [], 0)
            self.assertEqual(counted.scaled.call_count, PO.MAX_ACTIVE)
            self.assertLessEqual(PO._scaled_bytes(), PO.SCALED_BUDGET)
            self.assertEqual(len({k[0] for k in PO._scaled}), PO.MAX_ACTIVE)
        finally:
            painter.end()

    def test_stale_result_ignored_after_disable_and_reenable(self):
        images, delays = PO._decode(self.spec)
        old = dict(self.spec, epoch=1)
        new = dict(self.spec, epoch=2)
        future = concurrent.futures.Future()
        future.set_running_or_notify_cancel()
        PO._pending[PO.image_key(old)] = future
        PO.sync([])
        future.set_result((images, delays))
        with mock.patch.object(PO._pool, "submit", return_value=concurrent.futures.Future()):
            PO.sync([new])
        self.assertNotIn(PO.image_key(old), PO._decoded)
        self.assertNotIn(PO.image_key(new), PO._decoded)

    def test_phase_manual_grid_fallback_and_seeks(self):
        starts = [0.5, 1.0, 1.5, 2.0]
        s = {"beats": 8}
        self.assertAlmostEqual(PO.beat_at(1.25, starts), 1.5)
        self.assertAlmostEqual(PO.phase(2.5, s, 4.0, starts, 120), 0.5)
        self.assertAlmostEqual(PO.phase(2, s, 4.0, [], 120), 0.5)
        self.assertAlmostEqual(PO.phase(4, dict(s, fallback_bpm=60), 4.0, [], 0), 0.5)
        self.assertAlmostEqual(PO.phase(1, dict(s, bpm=240), 4.0, starts, 120), 0.5)
        self.assertEqual(PO.phase(0.5, s, 4.0, starts, 120), 0)
        self.assertEqual(PO.frame_at(0.5, [0.1, 0.2, 0.3]), 1)

    def test_uneven_beats_keep_a_steady_pace(self):
        # 120 bpm, each beat up to 50 ms early or late, as live-heard beats are:
        # the pace stays near two beats a second instead of following every gap.
        import random
        rnd = random.Random(7)
        starts = [1.0 + 0.5 * i + rnd.uniform(-0.05, 0.05) for i in range(60)]
        dt = 0.01
        times = [0.5 + dt * i for i in range(int(30.5 / dt))]
        beats = [PO.beat_at(t, starts) for t in times]
        speeds = [(b - a) / dt for a, b in zip(beats, beats[1:])]
        self.assertGreater(min(speeds), 1.9)          # each gap alone: 1.7..2.5
        self.assertLess(max(speeds), 2.1)
        self.assertLess(max(abs(b - a) for a, b in zip(beats, beats[1:])), 0.03)
        # Still on the beat: every detected beat is close to a whole beat.
        for i, s in enumerate(starts[5:-5], 5):
            self.assertAlmostEqual(PO.beat_at(s, starts), i, delta=0.15)
        # Deterministic from the position alone, so seeks land the same.
        self.assertEqual(PO.beat_at(12.34, starts), PO.beat_at(12.34, list(starts)))

    def test_dvd_reflects_at_edges_without_drifting(self):
        spec = dict(self.spec, motion="dvd", speed=100, corner="top-left", margin=10)
        # A 64px square in 400x300 leaves spans 316 and 216. Velocity 80,60.
        origin = PO.place(spec, 64, 64, 400, 300, 0)
        moved = PO.place(spec, 64, 64, 400, 300, 1)
        self.assertEqual((origin.x(), origin.y()), (10, 10))
        self.assertEqual((moved.x(), moved.y()), (90, 70))
        hit = 316 / 80
        before = PO.place(spec, 64, 64, 400, 300, hit - 0.1)
        at = PO.place(spec, 64, 64, 400, 300, hit)
        after = PO.place(spec, 64, 64, 400, 300, hit + 0.1)
        self.assertAlmostEqual(at.right(), 390)
        self.assertAlmostEqual(before.x(), after.x())
        self.assertLess(after.x(), at.x())
        # Repeated position is pause; seeking back reproduces the position.
        self.assertEqual(moved, PO.place(spec, 64, 64, 400, 300, 1))
        self.assertEqual(origin, PO.place(spec, 64, 64, 400, 300, 0))
        for corner in PL.CORNERS:
            for width, height in ((400, 300), (80, 60), (1, 1)):
                for pos in (0, 1, 10, 1000000):
                    rect = PO.place(dict(spec, corner=corner, margin=1000),
                                    48, 364, width, height, pos)
                    self.assertGreaterEqual(rect.left(), -1e-8)
                    self.assertGreaterEqual(rect.top(), -1e-8)
                    self.assertLessEqual(rect.right(), width + 1e-8)
                    self.assertLessEqual(rect.bottom(), height + 1e-8)

    def test_dvd_preserves_starting_corner_and_stationary_mode(self):
        for corner in PL.CORNERS:
            spec = dict(self.spec, corner=corner, margin=10)
            fixed = PO.place(spec, 64, 64, 400, 300)
            self.assertEqual(fixed, PO.place(spec, 64, 64, 400, 300, 100))
            self.assertEqual(fixed, PO.place(dict(spec, motion="dvd"), 64, 64, 400, 300, 0))
        self.assertEqual(PO.reflected(100, 0), 0)
        self.assertEqual(PO.reflected(125, 100), 75)
        self.assertEqual(PO.reflected(225, 100), 25)


if __name__ == "__main__":
    unittest.main()
