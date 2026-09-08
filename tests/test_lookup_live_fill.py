#!/usr/bin/env python3
"""Live-fill regression tests (user fix request, 2026-09-03).

A sheet row whose price cell is unusable ("unavailable <date>", N/A,
blank) must NOT dead-end the lookup chain: in compare auto mode
(non-interactive) the MISSING stores are live-searched and merged,
with sheet prices never overwritten and per-store (sheet)/(live)
labels preserved. Interactive callers (map resolve flow) keep the
pure sheet answer.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))
_ROOT = _PROJECT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.lookup import LookupEngine, LookupStatus  # noqa: E402
from extractors.models import ProductItem  # noqa: E402

HEADER = ["Product_Name", "Category", "Size",
          "Woolworths_Price", "Coles_Price", "Brand_Type",
          "Last_Updated", "Keywords"]

# Row 2: one-sided — Coles cell holds an unusable marker.
INCOMPLETE_ROW = ["Tip Top Bread 650g", "Bakery", "650g",
                  "$3.00", "unavailable 2026-08-01", "",
                  "2026-01-15 09:00", "bread"]

# Row 3: legacy unpriced — both cells unusable.
UNPRICED_ROW = ["Beef Mince 500g", "Meat", "500g",
                "unavailable 2026-08-01", "", "",
                "2026-01-15 09:00", "beef mince"]


class _FakeWorksheet:
    """Minimal get_all_values() stub (read-only tests)."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self._values]


def _engine(rows):
    return LookupEngine(worksheet=_FakeWorksheet([HEADER] + rows))


def _stub_live(ww_items, coles_items, coles_status="ok"):
    def stub_ww(query, page_size=5):
        return list(ww_items)

    def stub_coles(query, page_size=5):
        return (list(coles_items), coles_status)

    return patch(
        "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
        side_effect=stub_ww), patch(
        "extractors.coles_extractor.fetch_coles_search_status",
        side_effect=stub_coles)


class TestLiveFill(unittest.TestCase):
    """The one-sided/unpriced row live-fill (compare auto mode)."""

    def test_one_sided_row_live_fills_missing_store(self):
        # Both live sides return a size-comparable product; the WW
        # sheet price is kept and only the MISSING store is filled.
        ww = _stub_live([ProductItem("woolworths", "Tip Top Bread 650g",
                                     3.10, size="650g")],
                        [_live_coles()])
        with ww[0], ww[1]:
            result = _engine([INCOMPLETE_ROW]).find_product(
                "Tip Top Bread 650g", interactive=False)
        self.assertEqual(result.status, LookupStatus.SHEET_AND_LIVE)
        # Usable sheet price KEPT, missing store LIVE-FILLED.
        self.assertEqual(result.prices["woolworths"], 3.00)
        self.assertEqual(result.prices["coles"], 2.20)
        self.assertEqual(result.sources,
                         {"woolworths": "sheet", "coles": "live"})
        self.assertEqual(result.matched_names["woolworths"],
                         "Tip Top Bread 650g")
        self.assertEqual(result.matched_names["coles"],
                         "Coles Bakery White 650g")
        self.assertEqual(result.row_index, 2)  # sheet anchor kept

    def test_interactive_keeps_pure_sheet_answer(self):
        ww = _stub_live([], [_live_coles()])
        with ww[0], ww[1]:
            result = _engine([INCOMPLETE_ROW]).find_product(
                "Tip Top Bread 650g", interactive=True)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.prices, {"woolworths": 3.00})
        self.assertEqual(result.sources, {})  # never populated

    def test_complete_row_never_calls_live(self):
        complete = ["Full Cream Milk 2L", "Dairy", "2L",
                    "$3.00", "$2.80", "",
                    "2026-01-15 09:00", "milk"]
        ww = _stub_live([], [])
        with ww[0] as ww_mock, ww[1] as coles_mock:
            result = _engine([complete]).find_product(
                "Full Cream Milk 2L", interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.prices,
                         {"woolworths": 3.00, "coles": 2.80})
        ww_mock.assert_not_called()
        coles_mock.assert_not_called()

    def test_unpriced_row_live_fills_both_stores(self):
        # Same-size pair passes the UOM gate -> both stores filled.
        ww = _stub_live([_live_ww()],
                        [ProductItem("coles", "Coles Beef Mince 500g",
                                     7.50, size="500g")])
        with ww[0], ww[1]:
            result = _engine([UNPRICED_ROW]).find_product(
                "Beef Mince 500g", interactive=False)
        self.assertEqual(result.status, LookupStatus.SHEET_AND_LIVE)
        self.assertEqual(result.prices,
                         {"woolworths": 8.00, "coles": 7.50})
        self.assertEqual(set(result.sources.values()), {"live"})

    def test_pair_gate_still_rejects_mismatched_sizes(self):
        # 500g vs 650g is beyond the 20% tolerance -> the pair gate
        # rejects and the sheet answer is kept (no fabricated price).
        ww = _stub_live([_live_ww()], [_live_coles()])
        with ww[0], ww[1]:
            result = _engine([UNPRICED_ROW]).find_product(
                "Beef Mince 500g", interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.prices, {})

    def test_live_adds_nothing_returns_pure_sheet_answer(self):
        ww = _stub_live([], [])
        with ww[0], ww[1]:
            result = _engine([INCOMPLETE_ROW]).find_product(
                "Tip Top Bread 650g", interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.prices, {"woolworths": 3.00})

    def test_coles_unavailable_leaves_sheet_answer_intact(self):
        ww = _stub_live([], [], coles_status="unavailable")
        with ww[0], ww[1]:
            result = _engine([INCOMPLETE_ROW]).find_product(
                "Tip Top Bread 650g", interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.prices, {"woolworths": 3.00})
        self.assertNotIn("coles", result.store_unavailable)


def _live_ww():
    return ProductItem("woolworths", "WW Beef Mince 500g", 8.00,
                       size="500g")


def _live_coles():
    return ProductItem("coles", "Coles Bakery White 650g", 2.20,
                       size="650g")


class TestMixedPairUomGate(unittest.TestCase):
    """FIX-1 (defect D6): mixed sheet+live pairs must pass the UOM 20%
    band — the live fill must never pair a sheet 60g price with a live
    110g product (Sunbites case, outputs/T1.V09)."""

    # Row 2: Coles sheet price 60g; WW cell GONE (user verdict).
    SUNBITES_ROW = ["Sunbites Sour 60g", "Snacks", "60g",
                    "GONE", "$2.50", "",
                    "2026-01-15 09:00", "sunbites"]

    def test_mixed_pair_60g_vs_110g_rejected(self):
        # Sheet Coles 60g vs live WW 110g: 83% apart — the gate must
        # refuse the fill; the sheet answer is kept (no WW price).
        ww = _stub_live(
            [ProductItem(
                "woolworths",
                "Sunbites Biscuit Crackers Share Pack Sour Cream & "
                "Chives 110g", 3.50, size="110g")],
            [ProductItem("coles", "Sunbites Sour Cream 60g", 2.50,
                         size="60g")])
        with ww[0], ww[1]:
            result = _engine([self.SUNBITES_ROW]).find_product(
                "Sunbites Sour 60g", interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.prices, {"coles": 2.50})
        self.assertNotIn("woolworths", result.prices)

    def test_mixed_pair_60g_vs_70g_allowed(self):
        # 60g vs 70g is 16.7% — inside the 20% band: fill is allowed.
        ww = _stub_live(
            [ProductItem("woolworths", "Sunbites Sour 70g", 2.90,
                         size="70g")],
            [ProductItem("coles", "Sunbites Sour 60g", 2.50,
                         size="60g")])
        with ww[0], ww[1]:
            result = _engine([["Sunbites Sour 60g", "Snacks", "60g",
                               "", "$2.50", "",
                               "2026-01-15 09:00", "sunbites"]]
                             ).find_product("Sunbites Sour 60g",
                                            interactive=False)
        self.assertEqual(result.status, LookupStatus.SHEET_AND_LIVE)
        self.assertEqual(result.prices,
                         {"woolworths": 2.90, "coles": 2.50})
        self.assertEqual(result.sources,
                         {"woolworths": "live", "coles": "sheet"})

    def test_gone_cell_same_product_live_can_answer(self):
        # Option (b): a GONE verdict may be answered ONLY by the SAME
        # product (is_same_product) that also passes the UOM gate —
        # the item restocked at the verified-gone store.
        ww = _stub_live(
            [ProductItem("woolworths", "Sunbites Sour 60g", 2.60,
                         size="60g")],
            [ProductItem("coles", "Sunbites Sour 60g", 2.50,
                         size="60g")])
        with ww[0], ww[1]:
            result = _engine([self.SUNBITES_ROW]).find_product(
                "Sunbites Sour 60g", interactive=False)
        self.assertEqual(result.status, LookupStatus.SHEET_AND_LIVE)
        self.assertEqual(result.prices,
                         {"woolworths": 2.60, "coles": 2.50})

    def test_gone_cell_different_product_never_pairs(self):
        # Same size (60g) but a DIFFERENT product: the GONE verdict
        # stands — no silent substitution.
        ww = _stub_live(
            [ProductItem("woolworths", "Doritos Corn Chips 60g", 2.00,
                         size="60g")],
            [ProductItem("coles", "Sunbites Sour 60g", 2.50,
                         size="60g")])
        with ww[0], ww[1]:
            result = _engine([self.SUNBITES_ROW]).find_product(
                "Sunbites Sour 60g", interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.prices, {"coles": 2.50})

    def test_blank_cell_live_fill_still_gated_by_size(self):
        # Blank (never-priced) cell is NOT a GONE verdict — the fill
        # runs, but still through the size gate: 60g vs 1kg refused.
        ww = _stub_live(
            [ProductItem("woolworths", "Sunbites Party Pack 1kg", 9.00,
                         size="1kg")],
            [ProductItem("coles", "Sunbites Sour 60g", 2.50,
                         size="60g")])
        with ww[0], ww[1]:
            result = _engine(
                [["Sunbites Sour 60g", "Snacks", "60g",
                  "", "$2.50", "", "2026-01-15 09:00", "sunbites"]]
            ).find_product("Sunbites Sour 60g", interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.prices, {"coles": 2.50})


if __name__ == "__main__":
    unittest.main()
