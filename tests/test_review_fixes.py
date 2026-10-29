"""Regressions for a review sweep, runnable without Qt: methods defined twice
in one class."""
import ast
import collections
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def twice(path: str, cls: str) -> list[str]:
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    # A property's setter shares its getter's name on purpose.
    seen = collections.Counter(
        n.name for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not any(ast.unparse(d).endswith(('.setter', '.deleter')) for d in n.decorator_list))
    return sorted(k for k, v in seen.items() if v > 1)


class DefinedOnceTests(unittest.TestCase):
    # A second def silently replaces the first: ask_text returning a tuple
    # broke making and renaming playlists, eventFilter lost the drawer's resize.
    def test_lyrics_view(self):
        self.assertEqual(twice('mild-lyrics/lyrics_gui.py', 'LyricsView'), [])

    def test_home(self):
        self.assertEqual(twice('mild-lyrics/home_page.py', 'Home'), [])

    def test_editor(self):
        self.assertEqual(twice('editor/app.py', 'Editor'), [])


if __name__ == '__main__':
    unittest.main()
