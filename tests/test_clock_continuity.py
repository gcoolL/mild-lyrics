"""Clock arithmetic regressions, runnable without Qt or a music player."""
import ast
from pathlib import Path
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'mild-lyrics' / 'lyrics_gui.py'


def load_clock():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Clock')
    ns = dict(threading=threading, mono=lambda: 100., UNPAUSE_DELAY=0.,
              SEEK_JUMP=2., SLEW_MAX=.6, SLEW_TIME=.35, RESUME_SETTLE=1.,
              RESUME_MEASURE=0., STALE_HOLD=2.,
              follow_log=lambda *args, **kwargs: None)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(SOURCE), 'exec'), ns)
    return ns['Clock']


class ClockContinuityTests(unittest.TestCase):
    def setUp(self):
        self.clock = load_clock()(object())
        c = self.clock
        c.status = 'Playing'
        c.tid = c._pos_tid = c._bias_tid = 'test'
        c._at = 100.
        c._raw = c._pos = 10.

    def reading(self, at, pos, **extra):
        got = dict(tid='test', status='Playing', pos=pos, at=at,
                   meta={}, source='engine')
        got.update(extra)
        self.clock.apply(got, pin_pause=False)
        self.assertEqual(self.clock.status, got['status'])

    def test_overlapping_corrections_are_continuous(self):
        for interval in (.016, .05, .25):
            with self.subTest(interval=interval):
                self.setUp()
                for i in range(1, 61):
                    at = 100. + i * interval
                    before = self.clock.position(at)
                    self.reading(at, 10. + i * interval + (.1 if i % 2 else .12))
                    self.assertAlmostEqual(self.clock.position(at), before, places=9)

    def test_correction_converges_without_more_readings(self):
        self.reading(100.25, 10.35)
        self.assertAlmostEqual(self.clock.position(100.60), 10.70)

    def test_large_seek_discards_previous_slew(self):
        self.reading(100.25, 10.35)
        self.reading(100.30, 25.)
        self.assertAlmostEqual(self.clock.position(100.30), 25.)
        self.assertEqual(self.clock._slew, 0.)

    def test_new_track_discards_previous_slew(self):
        self.reading(100.25, 10.35)
        self.reading(100.30, 0., tid='next')
        self.assertAlmostEqual(self.clock.position(100.30), 0.)
        self.assertEqual(self.clock._slew, 0.)

    def test_pause_discards_previous_slew(self):
        self.reading(100.25, 10.35)
        self.reading(100.30, 10.4, status='Paused')
        self.assertEqual(self.clock._slew, 0.)
        self.assertAlmostEqual(self.clock.position(101.), 10.4)

    def test_audio_hold_discards_previous_slew(self):
        self.reading(100.25, 10.35)
        self.reading(100.30, 10.4, held=True)
        self.assertEqual(self.clock._slew, 0.)
        self.assertAlmostEqual(self.clock.position(101.), 10.4)


if __name__ == '__main__':
    unittest.main()
