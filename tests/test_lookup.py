#!/usr/bin/env python3
"""GROUP A — 15 scenarios for core/lookup.py state machine (LookupEngine).

Pure unit tests: no network, no live sheet. Uses FakeWorksheet mock.
Tests the full lookup chain: Steps 1->2->3->5->6 plus persist_alias (Step 4).

Usage:
    python grocery-price-tracker/tests/test_lookup.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Bootstrap sys.path so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent  # tests/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.lookup import (
    LookupEngine,
    LookupIndex,
    LookupStatus,
    LookupResult,
    CandidateRow,
    ALIAS_DELIM,
)

from extractors.models import ProductItem


# ============================================================================
# FakeWorksheet — mock gspread Worksheet for unit testing
# ============================================================================


def _col_letter_to_idx(letter: str) -> int:
    """'A'->0, 'Z'->25, 'AA'->26."""
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def _parse_range(range_name: str) -> tuple:
    """Parse 'A2:O83' -> (start_row, start_col, end_row, end_col). 1-based."""
    m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
    if not m:
        raise ValueError(f"Cannot parse range: {range_name}")
    sc = _col_letter_to_idx(m.group(1))
    sr = int(m.group(2))
    ec = _col_letter_to_idx(m.group(3))
    er = int(m.group(4))
    return sr, sc, er, ec


class FakeWorksheet:
    """Mock gspread Worksheet for unit testing."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]  # deep copy
        self.updates = []  # list of (values, range_name) tuples

    def get_all_values(self):
        return [list(r) for r in self._values]

    def update(self, *, values, range_name):
        self.updates.append((values, range_name))
        # Parse range and apply write to in-memory grid
        sr, sc, er, ec = _parse_range(range_name)
        for row_offset, row_vals in enumerate(values):
            r = sr + row_offset - 1  # 0-based row
            while len(self._values) <= r:
                self._values.append([])
            for col_offset, val in enumerate(row_vals):
                c = sc + col_offset
                while len(self._values[r]) <= c:
                    self._values[r].append("")
                self._values[r][c] = val


# ============================================================================
# Test fixtures — Products_Master with Col P (Keywords) aliases
# ============================================================================

# Full header with 16 columns (A-P)
FULL_HEADER = [
    "Product_Name",           # A
    "Category",               # B
    "Size",                   # C
    "Woolworths_Price",       # D
    "Coles_Price",            # E
    "Aldi_Price",             # F
    "Brand_Type",             # G
    "Last_Updated",           # H
    "Search_Keyword_Woolworths",  # I
    "Search_Keyword_Coles",   # J
    "Search_Keyword_Aldi",    # K
    "Aldi_Refresh",           # L
    "Woolworths_Specials",    # M
    "Coles_Specials",         # N
    "Rewards_Points",         # O
    "Keywords",               # P
]

FULL_ROWS = [
    # Row 2: Oat Milk — exact Col I keyword + Col P alias "oatly"
    ["Oat Milk", "Dairy", "1L", "$4.50", "$4.20", "",
     "Oatly", "2026-01-15 09:00",
     "Oatly Barista 1L", "", "", "",
     "Half Price", "", "", "oatly|barista milk"],
    # Row 3: Full Cream Milk — Col J keyword, no Col P alias
    ["Full Cream Milk", "Dairy", "2L", "$3.00", "$2.80", "",
     "", "2026-01-15 09:00",
     "", "Coles Full Cream Milk 2L", "", "",
     "", "", "", ""],
    # Row 4: Beef Mince — Col I keyword + Col P alias "beef mince"
    ["Beef Mince", "Meat", "500g", "$8.00", "$7.50", "",
     "Woolworths", "2026-01-15 09:00",
     "Woolworths Beef Mince 500g", "", "", "",
     "", "", "", "beef mince"],
    # Row 5: Cheese Block — Col I+J keywords + multiple Col P aliases
    ["Cheese Block", "Dairy", "500g", "$5.00", "$4.80", "",
     "Bega", "2026-01-15 09:00",
     "Bega Cheese Block 500g", "Bega Cheese Block 500g", "", "",
     "", "Half Price", "", "cheese|bega|tasty cheese"],
    # Row 6: Free Range Eggs — no store keywords, Col P alias only
    ["Free Range Eggs", "Dairy", "12pk", "", "", "",
     "", "2026-01-15 09:00",
     "", "", "", "",
     "", "", "", "free range eggs dozen"],
    # Row 7: Avocado — no keywords, no Col P alias (pure Col A match only)
    ["Avocado", "Fruit & Veg", "ea", "$2.50", "", "",
     "", "2026-01-15 09:00",
     "", "", "", "",
     "", "", "", ""],
]


def _make_worksheet_with_header(header=None, rows=None):
    """Build a FakeWorksheet with the standard fixtures."""
    hdr = header if header is not None else list(FULL_HEADER)
    rws = rows if rows is not None else FULL_ROWS
    return FakeWorksheet([hdr] + [list(r) for r in rws])


# ============================================================================
# GROUP A — 15 test scenarios
# ============================================================================


class TestLookupEngine(unittest.TestCase):
    """15 scenarios for the lookup.py state machine (LookupEngine)."""

    def setUp(self):
        """Create a fresh FakeWorksheet and LookupEngine for each test."""
        self.ws = _make_worksheet_with_header()
        self.engine = LookupEngine(worksheet=self.ws)

    # --- Scenario 1: Step 1 — exact Col A match ---
    def test_step1_exact_col_a_match(self):
        """Exact Col A match returns EXACT_SHEET with prices."""
        result = self.engine.find_product("Oat Milk")
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.row_index, 2)
        self.assertEqual(result.generic_name, "Oat Milk")
        self.assertEqual(result.prices["woolworths"], 4.50)
        self.assertEqual(result.prices["coles"], 4.20)
        self.assertIn("exact match", result.note)

    # --- Scenario 2: Step 1 — exact Col I/J/K keyword match ---
    def test_step1_exact_keyword_match(self):
        """Exact Col J keyword match returns EXACT_SHEET."""
        result = self.engine.find_product("Coles Full Cream Milk 2L")
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.row_index, 3)
        self.assertEqual(result.generic_name, "Full Cream Milk")
        self.assertIn("exact match", result.note)

    # --- Scenario 3: Step 1 — no match, proceeds to Step 2a ---
    def test_step2a_exact_alias_match(self):
        """Col P exact alias match returns KEYWORD_ALIAS."""
        result = self.engine.find_product("oatly")
        self.assertEqual(result.status, LookupStatus.KEYWORD_ALIAS)
        self.assertEqual(result.row_index, 2)
        self.assertEqual(result.generic_name, "Oat Milk")
        self.assertIn("Col P alias match", result.note)

    # --- Scenario 4: Step 2a — exact alias case-insensitive ---
    def test_step2a_alias_case_insensitive(self):
        """Col P alias match is case-insensitive."""
        result = self.engine.find_product("OATLY")
        self.assertEqual(result.status, LookupStatus.KEYWORD_ALIAS)
        self.assertEqual(result.row_index, 2)

    # --- Scenario 5: Step 2b — token alias match ---
    def test_step2b_token_alias_match(self):
        """Token match finds row via Col P subset."""
        result = self.engine.find_product("tasty")
        self.assertEqual(result.status, LookupStatus.KEYWORD_ALIAS)
        self.assertEqual(result.row_index, 5)
        self.assertEqual(result.generic_name, "Cheese Block")
        self.assertIn("Col P token match", result.note)

    # --- Scenario 6: Step 2b — multi-word token match ---
    def test_step2b_multi_word_token_match(self):
        """Multi-word query token-matches multi-word alias."""
        result = self.engine.find_product("free eggs")
        self.assertEqual(result.status, LookupStatus.KEYWORD_ALIAS)
        self.assertEqual(result.row_index, 6)
        self.assertEqual(result.generic_name, "Free Range Eggs")

    # --- Scenario 7: Step 3 — candidates found (interactive) ---
    def test_step3_candidates_interactive(self):
        """Partial match returns CANDIDATES status (interactive)."""
        # "full" partially matches "Full Cream Milk" and won't hit Col P
        result = self.engine.find_product("full", interactive=True)
        self.assertEqual(result.status, LookupStatus.CANDIDATES)
        self.assertGreater(len(result.candidates), 0)
        # Candidates should be CandidateRow instances
        self.assertIsInstance(result.candidates[0], CandidateRow)

    # --- Scenario 8: Step 3 — candidates non-interactive auto-pick ---
    def test_step3_candidates_non_interactive_auto_pick(self):
        """Non-interactive mode auto-picks top candidate."""
        result = self.engine.find_product("full", interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertIn("auto-picked", result.note)
        self.assertIsNotNone(result.row_index)
        self.assertIn("full", result.generic_name.lower())

    # --- Scenario 9: Step 3 — no candidates, proceeds to Step 5 ---
    def test_step3_no_candidates_proceeds_to_live(self):
        """No candidates → live search. UOM-passing pair priced both."""
        # Spec B2 (§3.2): the shown pair must pass the UOM gate — sizes
        # added to the fixtures so the pair is comparable.
        def stub_ww(query, page_size=5):
            return [ProductItem("woolworths", "WW Chocolate 200g", 4.50,
                                size="200g")]

        def stub_coles(query, page_size=5):
            return ([ProductItem("coles", "Coles Chocolate 200g", 4.20,
                                 size="200g")], "ok")

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_ww,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=stub_coles,
        ):
            result = self.engine.find_product("chocolate")
        self.assertEqual(result.status, LookupStatus.LIVE_SEARCH)
        self.assertIn("woolworths", result.prices)
        self.assertIn("coles", result.prices)
        self.assertGreater(len(result.live_items), 0)

    # --- Scenario 10: Step 5 — live search, Coles unavailable ---
    def test_step5_live_search_results(self):
        """Coles unavailable → Woolworths-only price (B4.3)."""
        def stub_ww(query, page_size=5):
            return [ProductItem("woolworths", "WW Bread 650g", 2.50,
                                size="650g")]

        def stub_coles(query, page_size=5):
            return ([], "unavailable")

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_ww,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=stub_coles,
        ):
            result = self.engine.find_product("bread")
        self.assertEqual(result.status, LookupStatus.LIVE_SEARCH)
        self.assertEqual(result.prices["woolworths"], 2.50)
        self.assertNotIn("coles", result.prices)
        self.assertEqual(result.store_unavailable, ["coles"])

    # --- Scenario 11: Step 6 — genuine not found ---
    def test_step6_not_found(self):
        """Both stores empty → NOT_FOUND."""
        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=lambda q, **kw: [],
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=lambda q, **kw: ([], "empty"),
        ):
            result = self.engine.find_product("xyzunknown")
        self.assertEqual(result.status, LookupStatus.NOT_FOUND)
        self.assertIn("no match", result.note)

    # --- Scenario 12: Step 4 — persist_alias writes to Col P ---
    def test_step4_persist_alias_writes_col_p(self):
        """persist_alias appends query to Col P."""
        # Row 7 (Avocado) has empty Col P
        result = self.engine.persist_alias("avo", 7, worksheet=self.ws)
        self.assertTrue(result["wrote"])
        self.assertIn("avo", result["aliases"])

        # Verify the write happened
        updated = self.ws.get_all_values()
        keywords_col = 15  # Col P
        self.assertIn("avo", str(updated[6][keywords_col]))

    # --- Scenario 13: Step 4 — persist_alias idempotent ---
    def test_step4_persist_alias_idempotent(self):
        """persist_alias does not duplicate an existing alias."""
        # Row 2 (Oat Milk) already has "oatly" in Col P
        result = self.engine.persist_alias("oatly", 2, worksheet=self.ws)
        self.assertFalse(result["wrote"])
        self.assertIn("already exists", result["error"])

    # --- Scenario 14: Step 4 — persist_alias on row with existing aliases ---
    def test_step4_persist_alias_appends_to_existing(self):
        """persist_alias appends to existing pipe-delimited aliases."""
        # Row 2 has "oatly|barista milk"
        result = self.engine.persist_alias("oat milk drink", 2, worksheet=self.ws)
        self.assertTrue(result["wrote"])
        self.assertIn("oat milk drink", result["aliases"])
        self.assertIn("oatly", result["aliases"])  # original preserved

    # --- Scenario 15: empty query → NOT_FOUND ---
    def test_empty_query_returns_not_found(self):
        """Empty query string returns NOT_FOUND."""
        result = self.engine.find_product("")
        self.assertEqual(result.status, LookupStatus.NOT_FOUND)
        self.assertIn("empty query", result.note)


class TestLookupIndexEdgeCases(unittest.TestCase):
    """Edge case tests for LookupIndex (empty rows, missing columns)."""

    def test_empty_rows_empty_index(self):
        """Empty data rows produce empty index."""
        idx = LookupIndex([], ["Product_Name"])
        self.assertIsNone(idx.find_exact("anything"))
        self.assertIsNone(idx.find_alias_exact("anything"))
        self.assertIsNone(idx.find_alias_token("anything"))
        self.assertEqual(idx.find_candidates("anything"), [])

    def test_missing_col_p_header(self):
        """Header without Keywords column still works."""
        short_header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        short_rows = [
            ["Milk", "Dairy", "2L", "3.00", "2.80", "",
             "", "", "milk", "", "", ""],
        ]
        idx = LookupIndex(short_rows, short_header)
        # Exact match still works
        row = idx.find_exact("Milk")
        self.assertIsNotNone(row)
        # Col P aliases don't exist
        self.assertIsNone(idx.find_alias_exact("milk"))

    def test_empty_keywords_cell(self):
        """Empty Col P cell produces no aliases."""
        header = ["Product_Name", "Keywords"]
        rows = [["Milk", ""]]
        idx = LookupIndex(rows, header)
        self.assertIsNone(idx.find_alias_exact("anything"))

    def test_get_row_returns_correct_dict(self):
        """get_row returns the correct row dict by 1-based index."""
        idx = LookupIndex(FULL_ROWS, FULL_HEADER)
        row = idx.get_row(2)  # Oat Milk
        self.assertIsNotNone(row)
        self.assertEqual(row["generic_name"], "Oat Milk")
        # Out of bounds
        self.assertIsNone(idx.get_row(999))


if __name__ == "__main__":
    unittest.main()
