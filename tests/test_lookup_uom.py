#!/usr/bin/env python3
"""Unit tests for lookup Step 5 rework: ranking + UOM pair gate (B2).

Covers plan matrix L-1..L-18. No network: both store search functions
are patched with in-memory ProductItem fixtures. Steps 1-4 get a
golden regression (L-18) to prove byte-identical behaviour.
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

from core.lookup import (  # noqa: E402
    LookupEngine,
    LookupIndex,
    LookupStatus,
    rank_live_results,
    select_live_pair,
)
from extractors.models import ProductItem  # noqa: E402

_WW = "extractors.woolworths_extractor.fetch_woolworths_search_noauth"
_COLES_STATUS = "extractors.coles_extractor.fetch_coles_search_status"


def _item(store, name, price, size="", special_desc="", is_special=False):
    """ProductItem fixture shorthand."""
    return ProductItem(
        store=store, raw_name=name, price=price, size=size,
        special_desc=special_desc, is_special=is_special)


# ---------------------------------------------------------------------------
# Minimal FakeWorksheet (mirrors tests.test_lookup.FakeWorksheet shape)
# ---------------------------------------------------------------------------

HEADER = [
    "Product_Name", "Category", "Size", "Woolworths_Price", "Coles_Price",
    "Aldi_Price", "Brand_Type", "Last_Updated",
    "Search_Keyword_Woolworths", "Search_Keyword_Coles", "Aldi_Refresh",
    "Woolworths_Specials", "Coles_Specials", "Rewards_Points", "Keywords",
]

ROWS = [
    HEADER,
    ["Garden Soil 25L", "Garden", "25L", "$20.90", "", "", "Debco",
     "2026-08-28", "", "", "", "", "", "", "soil"],
    ["Oat Milk 1L", "Dairy", "1L", "$3.20", "$3.50", "", "Woollies",
     "2026-08-28", "", "", "", "", "", "", "oatly|oat milk"],
    ["Aluminium Foil 30m", "Household", "30m", "$8.00", "", "", "",
     "2026-08-28", "", "", "", "", "", "", ""],
]


class _FakeWorksheet:
    """Minimal mock gspread Worksheet for unit testing."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]
        self.updates = []

    def get_all_values(self):
        return [list(r) for r in self._values]

    def update(self, values, range_name=None):
        self.updates.append((values, range_name))


def _engine():
    """Engine wired to a fresh FakeWorksheet (no network)."""
    return LookupEngine(worksheet=_FakeWorksheet(ROWS))


class TestRankLiveResults(unittest.TestCase):
    """L-1..L-4: tolerant relevance ranking."""

    def _items(self):
        return [
            _item("woolworths", "Chux Super Wipes 3pk", 4.0),
            _item("woolworths", "Garden Soil 25L", 20.9),
            _item("woolworths", "Debco 25L Garden Soil", 19.5),
        ]

    def test_l1_ranking_deterministic(self):
        """L-1: order = relevance desc, name asc; stable across shuffles."""
        ranked1 = rank_live_results("garden soil", self._items())
        import random
        shuffled = self._items()
        random.Random(7).shuffle(shuffled)
        ranked2 = rank_live_results("garden soil", shuffled)
        names1 = [i.raw_name for i in ranked1]
        names2 = [i.raw_name for i in ranked2]
        self.assertEqual(names1, names2)
        # Same token overlap -> difflib ratio favours the closer string.
        self.assertEqual(names1[0], "Garden Soil 25L")
        self.assertEqual(names1[1], "Debco 25L Garden Soil")

    def test_l2_ranking_never_rejects(self):
        """L-2: irrelevant item still ranked (last), returned."""
        ranked = rank_live_results("garden soil", self._items())
        self.assertEqual(len(ranked), 3)
        self.assertIn("Chux Super Wipes 3pk",
                      [i.raw_name for i in ranked])
        self.assertEqual(ranked[-1].raw_name, "Chux Super Wipes 3pk")

    def test_l3_singular_plural_normalised(self):
        """L-3: 'tomatoes' query ranks 'Tomato' item first."""
        items = [
            _item("woolworths", "Chux Wipes", 2.0),
            _item("woolworths", "Tomato Diced 400g", 1.5),
        ]
        ranked = rank_live_results("tomatoes", items)
        self.assertEqual(ranked[0].raw_name, "Tomato Diced 400g")

    def test_l4_small_typo_absorbed(self):
        """L-4: difflib absorbs a small typo; right item ranks first."""
        items = [
            _item("woolworths", "Chux Super Wipes", 2.0),
            _item("woolworths", "Garden Soil 25L", 20.0),
        ]
        ranked = rank_live_results("garden soyl", items)
        self.assertEqual(ranked[0].raw_name, "Garden Soil 25L")


class TestSelectLivePair(unittest.TestCase):
    """L-5..L-9: pairwise UOM gate + sanity ceiling."""

    def test_l5_top_ranked_pair_when_uom_passes(self):
        """L-5: top-ranked pair used when UOM passes."""
        ww = [_item("woolworths", "Debco 25L Garden Soil", 19.5, size="25L"),
              _item("woolworths", "Potting Mix 10L", 8.0, size="10L")]
        coles = [_item("coles", "Coles 30L Garden Soil", 8.4, size="30L"),
                 _item("coles", "Coles Potting Mix 10L", 6.0, size="10L")]
        pair = select_live_pair("garden soil", ww, coles)
        self.assertTrue(pair["pair_passed"])
        self.assertEqual(pair["ww"].raw_name, "Debco 25L Garden Soil")
        self.assertEqual(pair["coles"].raw_name, "Coles 30L Garden Soil")

    def test_l6_next_ranked_used_when_top_fails(self):
        """L-6: 10m vs 150m foil fails -> the 150m WW item is used."""
        ww = [_item("woolworths", "Aluminium Foil 10m", 2.0, size="10m"),
              _item("woolworths", "Aluminium Foil 150m", 9.0, size="150m")]
        coles = [_item("coles", "Coles Aluminium Foil 150m", 9.5,
                       size="150m")]
        pair = select_live_pair("aluminium foil", ww, coles)
        self.assertTrue(pair["pair_passed"])
        self.assertEqual(pair["ww"].size, "150m")
        self.assertEqual(pair["coles"].size, "150m")

    def test_l7_no_pair_passes_records_closest_and_reason(self):
        """L-7: no pair -> pair_passed False, reason from best attempt."""
        ww = [_item("woolworths", "Aluminium Foil 10m", 2.0, size="10m")]
        coles = [_item("coles", "Coles Aluminium Foil 150m", 9.5,
                       size="150m")]
        pair = select_live_pair("aluminium foil", ww, coles)
        self.assertFalse(pair["pair_passed"])
        self.assertEqual(pair["reason"], "beyond_20pct")
        self.assertEqual(pair["ww_ranked"][0].size, "10m")
        self.assertEqual(pair["coles_ranked"][0].size, "150m")

    def test_l8_sanity_ceiling_prefers_within_10x(self):
        """L-8: first 10x-passing pair beats an earlier wild pair."""
        ww = [_item("woolworths", "Garden Soil 25L", 1.00, size="25L"),
              _item("woolworths", "Coles Garden Soil 30L", 20.00,
                    size="30L")]
        coles = [_item("coles", "Coles 25L Garden Soil", 100.00,
                       size="25L")]
        pair = select_live_pair("garden soil", ww, coles)
        self.assertTrue(pair["pair_passed"])
        self.assertEqual(pair["ww"].price, 20.00)  # not the $1 wild pair

    def test_l9_no_10x_pair_uses_first_passing(self):
        """L-9: no 10x-passing pair -> first gate-passing pair used."""
        ww = [_item("woolworths", "Garden Soil 25L", 1.00, size="25L"),
              _item("woolworths", "Garden Soil 30L", 1.50, size="30L")]
        coles = [_item("coles", "Coles 25L Garden Soil", 100.00,
                       size="25L")]
        pair = select_live_pair("garden soil", ww, coles)
        self.assertTrue(pair["pair_passed"])
        self.assertEqual(pair["ww"].price, 1.00)  # first passing (walk order)


class TestFindProductStep5(unittest.TestCase):
    """L-10..L-16: find_product Step 5 outcomes (patched stores)."""

    def _run(self, ww_items, coles_result, query="garden soil"):
        """find_product with both store functions patched."""
        with patch(_WW, side_effect=lambda q, **kw: ww_items), \
                patch(_COLES_STATUS, side_effect=lambda q, **kw: coles_result):
            return _engine().find_product(query)

    def test_l10_seasol_regression_no_prices(self):
        """L-10: tool set vs Seasol 1.2L -> no prices, found-block data."""
        ww = [_item("woolworths", "3 Piece Garden Tool Set", 15.0, size="")]
        coles = ([_item("coles", "Seasol 1.2L", 12.0, size="1.2L")], "ok")
        result = self._run(ww, coles, query="tool set")
        self.assertEqual(result.status, LookupStatus.LIVE_SEARCH)
        self.assertEqual(result.prices, {})
        self.assertEqual(result.uom_reason, "missing_size")
        self.assertEqual(
            result.closest["woolworths"],
            {"name": "3 Piece Garden Tool Set", "size": ""})
        self.assertEqual(
            result.closest["coles"], {"name": "Seasol 1.2L", "size": "1.2L"})
        self.assertGreater(len(result.live_items), 0)

    def test_l11_garden_soil_within_20pct_pair_chosen(self):
        """L-11: 25L vs 30L -> pair chosen, both prices."""
        ww = [_item("woolworths", "Debco 25L Potting Mix", 19.5, size="25L")]
        coles = ([_item("coles", "Coles 30L Potting Mix", 8.4, size="30L")],
                 "ok")
        result = self._run(ww, coles, query="potting mix")
        self.assertEqual(result.prices["woolworths"], 19.5)
        self.assertEqual(result.prices["coles"], 8.4)
        self.assertEqual(result.uom_reason, "")

    def test_l12_one_store_empty_no_prices(self):
        """L-12: coles 0 hits -> no prices, closest from WW (IN-1)."""
        ww = [_item("woolworths", "WW Bread 650g", 2.50, size="650g")]
        result = self._run(ww, ([], "empty"), query="bread")
        self.assertEqual(result.prices, {})
        self.assertEqual(result.closest,
                         {"woolworths": {"name": "WW Bread 650g",
                                         "size": "650g"}})
        self.assertEqual(result.uom_reason, "no_results_coles")

    def test_l13_coles_unavailable_ww_only_price(self):
        """L-13: coles 'unavailable' -> WW price + store_unavailable."""
        ww = [_item("woolworths", "WW Bread 650g", 2.50, size="650g")]
        result = self._run(ww, ([], "unavailable"), query="bread")
        self.assertEqual(result.prices, {"woolworths": 2.50})
        self.assertNotIn("coles", result.prices)
        self.assertEqual(result.store_unavailable, ["coles"])
        self.assertEqual(result.closest, {})

    def test_l14_breaker_and_cap_behave_like_unavailable(self):
        """L-14: breaker_open / cap_exceeded -> same as unavailable."""
        ww = [_item("woolworths", "WW Bread 650g", 2.50, size="650g")]
        for status in ("breaker_open", "cap_exceeded"):
            result = self._run(ww, ([], status), query="bread")
            self.assertEqual(result.prices, {"woolworths": 2.50})
            self.assertEqual(result.store_unavailable, ["coles"])

    def test_l15_chosen_pair_prepended_to_live_items(self):
        """L-15: live_items = [chosen_ww, chosen_coles] + rest (IN-4)."""
        ww = [_item("woolworths", "Debco 25L Potting Mix", 19.5, size="25L"),
              _item("woolworths", "Potting Mix 25L Bonus", 18.0, size="25L")]
        coles = ([_item("coles", "Coles 30L Potting Mix", 8.4, size="30L")],
                 "ok")
        result = self._run(ww, coles, query="potting mix")
        self.assertIs(result.live_items[0].raw_name,
                      "Debco 25L Potting Mix")
        self.assertEqual(result.live_items[1].store, "coles")
        self.assertEqual(len(result.live_items), 3)

    def test_l16_matched_names_sizes_from_chosen(self):
        """L-16: matched_names/matched_sizes = the chosen pair."""
        ww = [_item("woolworths", "Debco 25L Potting Mix", 19.5, size="25L")]
        coles = ([_item("coles", "Coles 30L Potting Mix", 8.4, size="30L")],
                 "ok")
        result = self._run(ww, coles, query="potting mix")
        self.assertEqual(result.matched_names,
                         {"woolworths": "Debco 25L Potting Mix",
                          "coles": "Coles 30L Potting Mix"})
        self.assertEqual(result.matched_sizes,
                         {"woolworths": "25L", "coles": "30L"})


class TestStepsOneToFourRegression(unittest.TestCase):
    """L-17, L-18: sheet steps untouched (+ additive fields)."""

    def test_l17_sheet_hits_populate_matched_names_sizes(self):
        """L-17: Step 1/2 hits fill matched_names/sizes from Col A/C."""
        result = _engine().find_product("garden soil 25l")
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.matched_names,
                         {"woolworths": "Garden Soil 25L"})
        self.assertEqual(result.matched_sizes, {"woolworths": "25L"})
        # Step 2 (alias "oatly" -> Oat Milk 1L, priced both stores).
        result2 = _engine().find_product("oatly")
        self.assertEqual(result2.status, LookupStatus.KEYWORD_ALIAS)
        self.assertEqual(result2.matched_names,
                         {"woolworths": "Oat Milk 1L", "coles": "Oat Milk 1L"})
        self.assertEqual(result2.matched_sizes,
                         {"woolworths": "1L", "coles": "1L"})

    def test_l18_steps_one_to_four_golden(self):
        """L-18: Steps 1-4 outputs byte-identical to the pre-change state."""
        # Step 1 exact.
        r1 = _engine().find_product("garden soil 25l")
        self.assertEqual(
            (r1.status, r1.row_index, r1.generic_name, r1.prices,
             r1.specials, r1.brand, r1.candidates, r1.live_items, r1.note),
            (LookupStatus.EXACT_SHEET, 2, "Garden Soil 25L",
             {"woolworths": 20.90}, {}, "Debco", [], [],
             "exact match: 'Garden Soil 25L'"))
        # Step 2a exact alias.
        r2 = _engine().find_product("oatly")
        self.assertEqual(
            (r2.status, r2.row_index, r2.generic_name, r2.prices, r2.note),
            (LookupStatus.KEYWORD_ALIAS, 3, "Oat Milk 1L",
             {"woolworths": 3.20, "coles": 3.50},
             "Col P alias match: 'Oat Milk 1L'"))
        # Step 3 candidates.
        r3 = _engine().find_product("garden")
        self.assertEqual(r3.status, LookupStatus.CANDIDATES)
        self.assertGreater(len(r3.candidates), 0)
        self.assertEqual(r3.prices, {})
        self.assertEqual(r3.row_index, None)
        # Step 6 not found (both stores patched empty).
        with patch(_WW, side_effect=lambda q, **kw: []), \
                patch(_COLES_STATUS,
                      side_effect=lambda q, **kw: ([], "empty")):
            r6 = _engine().find_product("xyzunknown")
        self.assertEqual(r6.status, LookupStatus.NOT_FOUND)
        self.assertEqual(r6.prices, {})

    def test_normalize_and_alias_maps_untouched(self):
        """Sanity: LookupIndex matching structures unchanged."""
        idx = LookupIndex(ROWS[1:], HEADER)
        self.assertIsNotNone(idx.find_exact("oat milk 1l"))
        self.assertIsNotNone(idx.find_alias_exact("oatly"))
        self.assertIsNone(idx.find_alias_exact("nonexistent alias xyz"))


if __name__ == "__main__":
    unittest.main()
