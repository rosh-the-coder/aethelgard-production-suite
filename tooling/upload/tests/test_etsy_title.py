"""Etsy listing title sanitizer (colon-once rule)."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.dirname(HERE)
sys.path.insert(0, UPLOAD)

from etsy_api import _sanitize_etsy_title  # noqa: E402


class EtsyTitleSanitizeTests(unittest.TestCase):
    def test_keeps_single_colon(self):
        t = "Still Life: Balsam Apple and Vegetables Vintage Print"
        self.assertEqual(_sanitize_etsy_title(t), t)

    def test_collapses_extra_colons(self):
        raw = "Cabbage: Vintage Kitchen Print: Digital Download: Wall Art"
        out = _sanitize_etsy_title(raw)
        self.assertEqual(out.count(":"), 1)
        self.assertTrue(out.startswith("Cabbage:"))
        self.assertIn("Vintage Kitchen Print", out)

    def test_empty_falls_back(self):
        self.assertEqual(_sanitize_etsy_title("  "), "Digital Print")

    def test_truncates_to_140(self):
        raw = ("Oil Painting: " + ("cabbage still life printable wall art " * 8))
        out = _sanitize_etsy_title(raw)
        self.assertLessEqual(len(out), 140)
        self.assertEqual(out.count(":"), 1)


if __name__ == "__main__":
    unittest.main()
