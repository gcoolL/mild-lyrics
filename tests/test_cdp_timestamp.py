"""CDP timestamp regressions without a running Qt app or Spotify instance."""
import ast,math,threading,unittest
from pathlib import Path
from types import SimpleNamespace
SOURCE=Path(__file__).resolve().parents[1]/'mild-lyrics'/'lyrics_gui.py'

class CdpTimestampTests(unittest.TestCase):
    def sample(self, *, engine=32.7, engine_at=102.7, rate=1., platform='win32', sampled=1002.99):
        tree=ast.parse(SOURCE.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CdpTransport')
        ticks=iter([100.,103.])
        ns=dict(threading=threading,math=math,sys=SimpleNamespace(platform=platform),
                mono=lambda:next(ticks),time=SimpleNamespace(time=lambda:1003.),
                JS_STATE='',art_url=lambda x:x,ENGINE_SNAP=.5,ENGINE_TAU=.3,STALE_HOLD=2.)
        exec(compile(ast.Module(body=[cls],type_ignores=[]),str(SOURCE),'exec'),ns)
        c=ns['CdpTransport'](9222)
        got=dict(uri='spotify:track:test',title='test',playing=True,ctl=32.99,
                 engine=engine,engine_at=engine_at,engine_rate=rate,sampled_at=sampled)
        c._conn=lambda:SimpleNamespace(evaluate=lambda js:got)
        return c.read(False)

    def test_delayed_response_uses_sample_time(self):
        got=self.sample()
        self.assertAlmostEqual(got['at'],102.99)
        self.assertAlmostEqual(got['pos'],32.99)

    def test_control_fallback_uses_same_sample_time(self):
        got=self.sample(engine=None)
        self.assertAlmostEqual(got['at'],102.99)
        self.assertAlmostEqual(got['pos'],32.99)

    def test_zero_playback_rate_does_not_advance_engine(self):
        got=self.sample(rate=0.)
        self.assertAlmostEqual(got['pos'],32.7)

    def test_foreign_timestamp_domain_is_ignored(self):
        got=self.sample(engine_at=900000.)
        self.assertAlmostEqual(got['pos'],32.7)

    def test_linux_keeps_engine_position(self):
        got=self.sample(platform='linux')
        self.assertAlmostEqual(got['pos'],32.7)

    def test_legacy_response_uses_midpoint_fallback(self):
        self.assertAlmostEqual(self.sample(sampled=None)['at'], 101.5)

    def test_wall_clock_shift_is_clamped_to_request(self):
        self.assertAlmostEqual(self.sample(sampled=999.)['at'],100.)
        self.assertAlmostEqual(self.sample(sampled=1005.)['at'],103.)

if __name__=='__main__':unittest.main()
