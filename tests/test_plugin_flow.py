"""Plugin renderer flows (renderers.PluginScene._flow): where a page whose
vocals overlap the page still being sung takes over. Wrapping is stubbed to
a fixed number of words a row, so the cases are exact; offscreen Qt only for
the import. Run with python -m unittest discover -s tests."""

import bisect
import os
import pathlib
import sys
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "mild-lyrics"))
from PyQt6.QtWidgets import QApplication                          # noqa: E402

app = QApplication.instance() or QApplication([])
import renderers as RD                                            # noqa: E402

FM = types.SimpleNamespace(height=lambda: 20.0)
FLOW = {"rows": 4, "break": 6.0, "lead": 3.0, "hold": 2.0,
        "spacing": None, "first_fade": None}


def line(name: str, words: list) -> dict:
    """A flow line of (start, end) words, `name`0, `name`1, ..."""
    return {"name": name, "words": words, "start": None, "end": None,
            "new_page": False, "first": words[0][0], "last": words[-1][1]}


def scene_pages(*lines, per_row: int = 2) -> list:
    """The flow's pages, as PluginScene._pages orders them."""
    r = RD.PluginScene.__new__(RD.PluginScene)

    def rows(_sc, ln, _px, _width):
        frags = [(0.0, 10.0, f"{ln['name']}{n}", s, e)
                 for n, (s, e) in enumerate(ln["words"])]
        cut = [frags[k:k + per_row] for k in range(0, len(frags), per_row)]
        return None, FM, cut, [10.0 * len(c) for c in cut]

    r._rows = rows
    r._face = lambda _sc, _ln, _px: (None, FM)
    pages = r._flow({"spacing": 1.2}, dict(FLOW, lines=list(lines)), 600, 2000, 30)
    return sorted(pages, key=lambda pg: pg["from"])


def shown_at(pages: list, pos: float) -> set:
    """The words on screen at `pos`, by the paint's own rule."""
    froms = [pg["from"] for pg in pages]
    k = bisect.bisect_right(froms, pos) - 1
    if k < 0 or pos >= pages[k]["to"]:
        return set()
    return {frag[2] for b in pages[k]["blocks"] for row in b[3] for frag in row}


class FlowHandoverTests(unittest.TestCase):
    def test_early_adlib_does_not_cut_a_long_wrapped_lead(self):
        # Twelve words 10..22, two a row: six rows, so a page of four and a
        # page of two; an ad-lib at 12..13 lands with the second. Turning at
        # the ad-lib hid the lead's words 2..7 while they were being sung.
        lead = line("lead", [(10.0 + n, 11.0 + n) for n in range(12)])
        adlib = line("adlib", [(12.0, 13.0)])
        pages = scene_pages(lead, adlib)
        for n in range(12):
            mid = 10.5 + n
            self.assertIn(f"lead{n}", shown_at(pages, mid), f"lead{n} at {mid}")

    def test_page_sung_entirely_under_the_last_is_left_out(self):
        # The ad-lib's own page would only ever show after it was sung, and
        # sitting at its from would blank the window: it is dropped instead.
        lead = line("lead", [(10.0 + n, 11.0 + n) for n in range(8)])
        adlib = line("adlib", [(12.0, 13.0)])
        pages = scene_pages(lead, adlib)
        self.assertEqual(len(pages), 1)
        for n in range(8):
            self.assertIn(f"lead{n}", shown_at(pages, 10.5 + n))
        self.assertTrue(shown_at(pages, 18.5))              # held, not blanked

    def test_long_overlapping_page_takes_over_early(self):
        # The old page has half a second left; the new one sings three seconds
        # under it. Holding the old page would hide more, so it turns early.
        old = line("old", [(8.0 + n, 9.0 + n) for n in range(7)] + [(15.0, 15.5)])
        new = line("new", [(12.0 + n * 0.5, 12.5 + n * 0.5) for n in range(8)])
        pages = scene_pages(old, new)
        self.assertEqual(len(pages), 2)
        self.assertLess(pages[1]["from"], 15.0)
        for n in range(8):
            mid = 12.25 + n * 0.5
            self.assertIn(f"new{n}", shown_at(pages, mid), f"new{n} at {mid}")

    def test_without_overlap_pages_turn_as_before(self):
        a = line("a", [(10.0 + n, 11.0 + n) for n in range(8)])
        b = line("b", [(20.0 + n, 21.0 + n) for n in range(4)])
        pages = scene_pages(a, b)
        self.assertEqual([(pg["from"], pg["to"]) for pg in pages],
                         [(7.0, 18.0), (18.0, 26.0)])

    def test_handover_weighs_both_pages(self):
        h = RD.PluginScene._handover
        self.assertEqual(h([(10, 18)], [(12, 13)], 12, 18), 18)
        self.assertEqual(h([(10, 12.5)], [(11, 15)], 11, 12.5), 11)
        self.assertEqual(h([(10, 14)], [(12, 16)], 12, 14), 12)     # tie: earliest


if __name__ == "__main__":
    unittest.main()
