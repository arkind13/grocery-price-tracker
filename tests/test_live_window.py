#!/usr/bin/env python3
"""Tests for the live-window offline pieces (Part C).

Matrix F (this module's first class): snapshot conversion for
extractors/live_list_fetch.py — all file-based, NO network, NO browser.
Matrices W (session logic) and D (automation assets) join later
classes in this same file per plan IN-7.
"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors import live_list_fetch as llf  # noqa: E402
from extractors.models import ProductItem  # noqa: E402


def _ww_item(name="WW Milk 2L", price=3.50, stockcode=123456, **extra):
    """Raw WW list-API product dict fixture."""
    item = {
        "Stockcode": stockcode,
        "DisplayName": name,
        "Price": price,
        "PackageSize": "2L",
        "Brand": "Pura",
    }
    item.update(extra)
    return item


def _coles_item(name="Coles Milk 2L", price=3.20, pid="998877", **extra):
    """Raw Coles product dict fixture (search-result shape)."""
    item = {
        "_type": "PRODUCT",
        "name": name,
        "id": pid,
        "size": "2L",
        "pricing": {"now": price},
    }
    item.update(extra)
    return item


class TestSnapshotConversion(unittest.TestCase):
    """Matrix F-1..F-10: offline snapshot loading + validation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.snapshots = tmp / "live_snapshots"
        self.snapshots.mkdir()
        self._patchers = [
            patch.object(llf, "SNAPSHOTS_DIR", self.snapshots),
            patch.object(llf, "DATA_DIR", tmp),
        ]
        for p in self._patchers:
            p.start()
        self.date = "2026-09-02"

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def write_ww(self, payload, slug="pricecompare"):
        """Write a WW snapshot file."""
        path = llf.ww_snapshot_path(self.date, slug)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_coles(self, payload):
        """Write a Coles snapshot file."""
        path = llf.coles_snapshot_path(self.date)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    # -- matrix ----------------------------------------------------------
    def test_f1_ww_specials_semantics(self):
        """F-1: IsOnSpecial/WasPrice/SavingsAmount -> extractor strings."""
        payload = [
            _ww_item(name="A", WasPrice=4.00, IsOnSpecial=True),
            _ww_item(name="B", stockcode=2, IsHalfPrice=True),
            _ww_item(name="C", stockcode=3, SavingsAmount=0.50,
                     IsOnSpecial=True),
            _ww_item(name="D", stockcode=4),
        ]
        items = llf.load_ww_snapshot(self.write_ww(payload))
        self.assertEqual(items[0].special_desc, "Was $4.00")
        self.assertEqual(items[1].special_desc, "Half Price")
        self.assertEqual(items[2].special_desc, "Save $0.50")
        self.assertEqual(items[3].special_desc, "")
        self.assertTrue(items[0].is_special)
        self.assertFalse(items[3].is_special)

    def test_f2_coles_snapshot_via_parse_search_result(self):
        """F-2: Coles fixture -> ProductItems (price/special/size)."""
        payload = [
            _coles_item(),
            {"_type": "BANNER", "name": "Half price sale"},  # filtered
        ]
        items = llf.load_coles_snapshot(self.write_coles(payload))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw_name, "Coles Milk 2L")
        self.assertEqual(items[0].price, 3.20)
        self.assertEqual(items[0].size, "2L")

    def test_f3_multipage_dedup_by_product_id(self):
        """F-3: same id across pages/boundaries appears once (DELTA-2)."""
        page1 = [_ww_item(name="WW Milk 2L", stockcode=111)]
        page2 = [_ww_item(name="WW Milk 2L", stockcode=111),
                 _ww_item(name="WW Bread", stockcode=222)]
        # Both pages land in one snapshot list; cross-page dedup applies.
        self.write_ww(page1 + page2)
        items = llf.load_ww_snapshot(
            llf.ww_snapshot_path(self.date, "pricecompare"))
        ids = [i.product_id for i in items]
        self.assertEqual(ids.count("111"), 1)
        self.assertEqual(len(items), 2)

    def test_f4_snapshots_for_date_returns_both_stores(self):
        """F-4: snapshots_for_date returns both stores' items."""
        self.write_ww([_ww_item()])
        self.write_coles([_coles_item()])
        snaps = llf.snapshots_for_date(self.date)
        self.assertEqual(len(snaps["woolworths"]), 1)
        self.assertEqual(len(snaps["coles"]), 1)
        self.assertEqual(snaps["woolworths"][0].store, "woolworths")
        self.assertEqual(snaps["coles"][0].store, "coles")

    def test_f5_validate_complete_names_missing_files(self):
        """F-5: missing files -> ValueError naming the exact file(s)."""
        with self.assertRaises(ValueError) as ctx:
            llf.validate_complete(self.date)
        msg = str(ctx.exception)
        self.assertIn(f"{self.date}_ww_pricecompare.json", msg)
        self.assertIn(f"{self.date}_coles_pricecompare.json", msg)

    def test_f6_specials_from_live_filters_specials(self):
        """F-6: specials_from_live filters the Special-list snapshot."""
        self.write_ww([_ww_item(name="A", IsOnSpecial=True, WasPrice=4.0)],
                      slug="speciallist28")
        self.write_ww([_ww_item(name="B")], slug="pricecompare")
        specials = llf.specials_from_live(self.date)
        self.assertEqual(len(specials), 1)
        self.assertEqual(specials[0].raw_name, "A")
        # No specials file at all -> empty (caller warns instead).
        self.assertEqual(llf.specials_from_live("1999-01-01"), [])

    def test_f7_corrupt_snapshot_valueerror_not_crash(self):
        """F-7: corrupt snapshot -> ValueError naming the file."""
        path = self.write_ww("this is not json {")
        with self.assertRaises(ValueError) as ctx:
            llf.load_ww_snapshot(path)
        self.assertIn(path.name, str(ctx.exception))

    def test_f8_id_missing_falls_back_to_name_dedup(self):
        """F-8: id-missing items dedup by normalised name."""
        payload = [
            _ww_item(name="WW Milk 2L", stockcode=None),
            _ww_item(name="ww  MILK 2l", stockcode=None),
        ]
        items = llf.load_ww_snapshot(self.write_ww(payload))
        self.assertEqual(len(items), 1)

    def test_f9_quantity_does_not_duplicate(self):
        """F-9: WW list Quantity never duplicates items."""
        payload = [_ww_item(name="WW Milk 2L", Quantity=3)]
        items = llf.load_ww_snapshot(self.write_ww(payload))
        self.assertEqual(len(items), 1)

    def test_f10_loader_never_touches_network(self):
        """F-10: loaders make no requests calls (offline by construction)."""
        self.write_ww([_ww_item()])
        self.write_coles([_coles_item()])
        import requests
        with patch.object(requests, "get",
                          side_effect=AssertionError("network!")):
            snaps = llf.snapshots_for_date(self.date)
        self.assertEqual(len(snaps["woolworths"]), 1)
        self.assertEqual(len(snaps["coles"]), 1)
        # Guardrail 5: no Scrape.do reference anywhere in this module.
        source = open(llf.__file__, encoding="utf-8").read().lower()
        self.assertNotIn("scrape.do", source)


if __name__ == "__main__":
    unittest.main()
