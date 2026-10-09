"""core/board_feed.py — ALDI_Specials_Feed writer tests (2026-10-09).
Fixtures mirror the REAL promotion tree shape (keys = drop dates) and
item fields from extractors.aldi_extractor. Offline: FakeWS/FakeSheet
doubles (test_v2_wednesday harness pattern), zero network."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.board_feed import (                      # noqa: E402
    ALDI_FEED_HEADER, ALDI_FEED_TAB, build_aldi_feed_rows,
    drop_end_date, next_drop_after, write_aldi_feed,
)
from extractors.models import ProductItem         # noqa: E402

# REAL promotion-tree shape (live probe 2026-10-09)
TREE = [
    {"key": "2026-10-07", "title": "Available from Wed 7th October"},
    {"key": "2026-10-14", "title": "Available from Wed 14th October"},
    {"key": "2026-10-17", "title": "Available from Sat 17th October"},
    {"key": "2026-10-21", "title": "Available from Wed 21st October"},
]


def _item(name, price=9.99, size="500 g", brand="", unit_price="",
          special_desc="", themes=None):
    it = ProductItem(store="aldi", raw_name=name, price=price,
                     size=size, brand=brand, unit_price=unit_price,
                     special_desc=special_desc)
    it._theme_categories = themes if themes is not None \
        else ["Grocery Specials"]
    return it


class FakeWS:
    def __init__(self, rows=None):
        self._values = [list(r) for r in (rows or [])]
        self.clears = 0
        self.updates = []

    def clear(self):
        self.clears += 1

    def update(self, *, values, range_name):
        self.updates.append(range_name)
        self._values = [list(r) for r in values]


class FakeSheet:
    def __init__(self):
        self.tabs: dict[str, FakeWS] = {}

    def worksheet(self, name):
        if name not in self.tabs:
            raise KeyError(name)
        return self.tabs[name]

    def add_worksheet(self, title, rows, cols):
        self.tabs[title] = FakeWS()
        return self.tabs[title]


class TestPure(unittest.TestCase):
    def test_next_drop_after_picks_earliest_later_key(self):
        self.assertEqual(next_drop_after(TREE, "2026-10-07"),
                         "2026-10-14")
        self.assertEqual(next_drop_after(TREE, "2026-10-17"),
                         "2026-10-21")
        self.assertEqual(next_drop_after(TREE, "2026-10-21"), None)

    def test_drop_end_date_is_day_before_next_drop(self):
        # REAL current case: Wed 7 Oct drop runs to Tue 13 Oct
        self.assertEqual(drop_end_date(TREE, "2026-10-07"),
                         "2026-10-13")
        # last known drop: +6 fallback
        self.assertEqual(drop_end_date(TREE, "2026-10-21"),
                         "2026-10-27")

    def test_row_shape_carries_real_theme_and_fields(self):
        rows = build_aldi_feed_rows(
            [_item("Salmon Gravalax 250g", 10.99, size="250 g",
                   unit_price="$44.00 per kg", themes=["Limited Time Only Meat"])],
            "Available from Wed 7th October", "2026-10-07", "2026-10-13")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r[0], "Salmon Gravalax 250g")
        self.assertEqual(r[1], "10.99")
        self.assertEqual(r[2], "250 g")
        self.assertEqual(r[4], "$44.00 per kg")
        self.assertEqual(r[6], "Limited Time Only Meat")
        self.assertEqual(r[7], "2026-10-07")
        self.assertEqual(r[8], "2026-10-13")
        self.assertEqual(r[9], "Available from Wed 7th October")

    def test_unpriced_item_keeps_blank_price(self):
        rows = build_aldi_feed_rows(
            [_item("Mystery Item", None)], "t", "2026-10-07", None)
        self.assertEqual(rows[0][1], "")
        self.assertEqual(rows[0][8], "")    # ends passthrough blank

    def test_no_theme_defaults_to_special_buys(self):
        # REAL 2026-10-07 drop: 47 of 84 items carry no categories —
        # the Telegram render's "Special Buys" default, never ""
        rows = build_aldi_feed_rows(
            [_item("Themeless Item", 5.00, themes=[])],
            "t", "2026-10-07", "2026-10-09")
        self.assertEqual(rows[0][6], "Special Buys")


class TestWrite(unittest.TestCase):
    def test_full_rewrite_creates_tab_with_header_and_rows(self):
        sheet = FakeSheet()
        items = [_item("A", 1.00), _item("B", 2.00)]
        with patch("extractors.aldi_extractor.fetch_promotion_tree",
                   return_value=TREE), \
             patch("core.sheets_client.connect_spreadsheet",
                   return_value=sheet):
            n = write_aldi_feed(items, TREE[0], "2026-10-07")
        self.assertEqual(n, 2)
        ws = sheet.tabs[ALDI_FEED_TAB]
        self.assertEqual(ws.clears, 1)
        self.assertEqual(ws.updates, ["A1:J3"])
        self.assertEqual(ws._values[0], ALDI_FEED_HEADER)
        self.assertEqual(ws._values[1][8], "2026-10-13")   # real end
        self.assertEqual(ws._values[1][9], "Available from Wed 7th October")

    def test_connect_failure_returns_minus_one_never_raises(self):
        with patch("extractors.aldi_extractor.fetch_promotion_tree",
                   return_value=TREE), \
             patch("core.sheets_client.connect_spreadsheet",
                   side_effect=RuntimeError("no creds")):
            self.assertEqual(
                write_aldi_feed([_item("A", 1.0)], TREE[0],
                                "2026-10-07"), -1)


if __name__ == "__main__":
    unittest.main()
