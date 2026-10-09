"""core/board_llm.py — GLM categorisation tests (2026-10-09, user ask:
"pass the aldi list through a llm (z.ai coding plan GLM-5.3 Flash) to
sort into categories"). Offline: parser + fallback laws. The LIVE call
is exercised by the real backfill (live-fire rule: the real GLM
response shape is pinned below, captured from the 2026-10-07 drop)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.board_llm import (                    # noqa: E402
    CATEGORIES, categorize, parse_categories,
)
from extractors.models import ProductItem       # noqa: E402


def _item(name, brand="", size="", themes=None):
    it = ProductItem(store="aldi", raw_name=name, price=9.99,
                     size=size, brand=brand)
    it._theme_categories = themes if themes is not None else []
    return it


class TestParser(unittest.TestCase):
    def test_real_glm_reply_shape_parses_by_index(self):
        # captured shape from the live glm-5.3-flash run (numbered
        # lines, vocabulary categories, occasional blank line)
        reply = """
1. Pantry & Grocery
2. Personal Care

3. Christmas & Seasonal
4. meat & seafood
"""
        out = parse_categories(reply, 4)
        self.assertEqual(out, ["Pantry & Grocery", "Personal Care",
                               "Christmas & Seasonal", "Meat & Seafood"])

    def test_unknown_category_text_becomes_none_never_garbage(self):
        out = parse_categories("1. Martian Supplies\n2. Drinks", 2)
        self.assertEqual(out, [None, "Drinks"])

    def test_lenient_bullets_and_parens(self):
        out = parse_categories("- 1) Snacks & Sweets\n  2. Drinks", 2)
        self.assertEqual(out, ["Snacks & Sweets", "Drinks"])

    def test_missing_lines_stay_none(self):
        out = parse_categories("1. Drinks", 3)
        self.assertEqual(out, ["Drinks", None, None])

    def test_vocabulary_is_board_friendly(self):
        self.assertIn("Meat & Seafood", CATEGORIES)
        self.assertIn("Christmas & Seasonal", CATEGORIES)
        self.assertIn("Other", CATEGORIES)
        self.assertLessEqual(len(CATEGORIES), 25)


class TestCategorizeFallbacks(unittest.TestCase):
    def test_no_key_returns_empty_silently(self):
        with patch("core.board_llm._env_or_file", return_value=None):
            self.assertEqual(categorize([_item("X")]), [])

    def test_any_failure_returns_empty_never_raises(self):
        import urllib.request
        with patch("core.board_llm._env_or_file",
                   side_effect=lambda n: "k" if n == "ZAI_API_KEY"
                   else None), \
             patch.object(urllib.request, "urlopen",
                          side_effect=TimeoutError("slow")):
            self.assertEqual(categorize([_item("X"), _item("Y")]), [])


class TestBuilderIntegration(unittest.TestCase):
    def test_feed_rows_carry_llm_category_with_theme_fallback(self):
        from core.board_feed import build_aldi_feed_rows
        items = [_item("Salmon Gravalax 250g", themes=["Meat & Seafood"]),
                 _item("Shaving Cream", themes=[]),
                 _item("Christmas Pudding", themes=["Christmas"])]
        cats = ["Meat & Seafood", "Personal Care", None]
        rows = build_aldi_feed_rows(items, "t", "2026-10-07",
                                    "2026-10-09", cats)
        self.assertEqual(rows[0][11], "Meat & Seafood")   # LLM cat
        self.assertEqual(rows[0][6], "Meat & Seafood")    # raw theme
        self.assertEqual(rows[1][11], "Personal Care")    # themeless→LLM
        self.assertEqual(rows[1][6], "Special Buys")      # theme default
        self.assertEqual(rows[2][11], "")                 # None → blank
        self.assertEqual(rows[2][6], "Christmas")         # app falls back


if __name__ == "__main__":
    unittest.main()
