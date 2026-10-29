"""The updater keeps a release's files inside its folder; runnable without Qt."""
import contextlib
import io
import pathlib
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


class UpdaterContainmentTests(unittest.TestCase):
    def test_archive_names_stay_inside(self):
        sys.path.insert(0, str(ROOT / 'mild-lyrics'))
        try:
            import updater as U
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            install = base / 'install'
            install.mkdir()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as z:
                # A drive name such as "C:x" passes the PurePosixPath checks;
                # on Windows another drive's letter would land outside.
                for n in ('o-r-sha/mild-lyrics/lyrics_gui.py', 'o-r-sha/ok/file.py',
                          'o-r-sha/a/../../evil2.py', 'o-r-sha/C:evil3.py'):
                    z.writestr(n, 'x')
            data = buf.getvalue()
            was = U.ROOT, U._open
            U.ROOT = install
            U._open = lambda req, t: contextlib.closing(io.BytesIO(data))
            try:
                ok, _ = U._install_zip({'tag': 't', 'zip': 'http://x'}, lambda s: None)
            finally:
                U.ROOT, U._open = was
            self.assertTrue(ok)
            got = sorted(p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file())
            self.assertEqual(got, ['install/mild-lyrics/lyrics_gui.py', 'install/ok/file.py'])


if __name__ == '__main__':
    unittest.main()
