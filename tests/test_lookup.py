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
    """"A'->0, 'Z'->25, 'AA'->26."""
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


class TestPluralTokenMatching(unittest.TestCase):
    """Singular/plural token matching (user report 2026-09-03: the
    basket query "apples" must find the sheet row "Royal Gala Apple
    1 Kg" whose Col P alias is "royal gala apple")."""

    def setUp(self):
        header = ["Product_Name", "Category", "Size",
                  "Woolworths_Price", "Coles_Price", "Brand_Type",
                  "Last_Updated", "Search_Keyword_Woolworths",
                  "Search_Keyword_Coles", "Keywords"]
        rows = [
            # Row 2: alias "royal gala apple" (singular "apple")
            ["Royal Gala Apple 1 Kg", "Fruit & Veg", "1kg",
             "$7.90", "N/A 2026-09-02", "",
             "2026-01-15 09:00", "Woolworths Royal Gala Apple Punnet 1kg",
             "Coles Royal Gala Apples 1kg", "royal gala apple"],
            # Row 3: plural alias "beef mince" style
            ["Beef Mince 500g", "Meat", "500g",
             "", "", "",
             "2026-01-15 09:00", "", "", "beef mince"],
        ]
        self.idx = LookupIndex(rows, header)

    def test_alias_token_plural_query_matches_singular_alias(self):
        row = self.idx.find_alias_token("apples")
        self.assertIsNotNone(row)
        self.assertEqual(row["generic_name"], "Royal Gala Apple 1 Kg")

    def test_alias_token_singular_query_matches_plural_alias(self):
        row = self.idx.find_alias_token("apple")
        self.assertIsNotNone(row)
        self.assertEqual(row["generic_name"], "Royal Gala Apple 1 Kg")

    def test_alias_token_ies_plural_matches_y(self):
        idx = LookupIndex(
            [["Cherry 200g", "Fruit", "200g", "", "", "",
              "", "", "", "cherry"]],
            ["Product_Name", "Category", "Size", "Woolworths_Price",
             "Coles_Price", "Brand_Type", "Last_Updated",
             "Search_Keyword_Woolworths", "Search_Keyword_Coles",
             "Keywords"])
        self.assertIsNotNone(idx.find_alias_token("cherries"))

    def test_candidates_plural_query_finds_singular_col_a(self):
        cands = self.idx.find_candidates("apples")
        self.assertTrue(cands)
        self.assertEqual(cands[0].generic_name, "Royal Gala Apple 1 Kg")

    def test_non_matching_query_still_returns_none(self):
        self.assertIsNone(self.idx.find_alias_token("socks"))


class TestLookupQRSMetadata(unittest.TestCase):
    """Additive Col Q/R/S metadata (spec §9 + plan §S10)."""

    HEADER_A_S = [
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
        "Sub_Category",           # Q
        "Item_Code",              # R
        "Preferred",              # S
    ]

    def _ws(self):
        rows = [
            self.HEADER_A_S,
            ["Oat Milk", "Dairy", "1L", "$4.50", "$4.20", "",
             "Oatly", "2026-01-15 09:00",
             "Oatly Barista 1L", "", "", "",
             "Half Price", "", "", "oatly", "milk", "abc", "P"],
            ["Sourdough", "Bakery", "650g", "$3.00", "", "",
             "", "2026-01-15 09:00",
             "", "", "", "",
             "", "", "", "", "bread", "", ""],
        ]
        return FakeWorksheet(rows)

    def test_index_carries_qrs_metadata(self):
        idx = LookupIndex(self._ws().get_all_values()[1:],
                          self.HEADER_A_S)
        row = idx.get_row(2)
        self.assertEqual(row["subcategory"], "milk")
        self.assertEqual(row["item_code"], "ABC")  # uppercased
        self.assertEqual(row["preferred"], "P")
        empty = idx.get_row(3)
        self.assertEqual(empty["subcategory"], "bread")
        self.assertEqual(empty["item_code"], "")
        self.assertEqual(empty["preferred"], "")

    def test_candidates_carry_subcategory_and_code(self):
        idx = LookupIndex(self._ws().get_all_values()[1:],
                          self.HEADER_A_S)
        cands = idx.find_candidates("oat milk")
        self.assertTrue(cands)
        top = cands[0]
        self.assertEqual(top.subcategory, "milk")
        self.assertEqual(top.item_code, "ABC")
        self.assertEqual(top.preferred, "P")

    def test_result_metadata_absent_headers_empty(self):
        # 16-col fixture (no Q/R/S headers): engine resolves Step 1
        # and the result metadata stays "" (absence-tolerant).
        ws = _make_worksheet_with_header()
        engine = LookupEngine(worksheet=ws)
        result = engine.find_product("oat milk", interactive=True)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.subcategory, "")
        self.assertEqual(result.item_code, "")
        self.assertEqual(result.preferred, "")

    def test_result_carries_resolved_row_metadata(self):
        engine = LookupEngine(worksheet=self._ws())
        result = engine.find_product("oat milk", interactive=True)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)
        self.assertEqual(result.subcategory, "milk")
        self.assertEqual(result.item_code, "ABC")
        self.assertEqual(result.preferred, "P")


class TestHalalIntercept(unittest.TestCase):
    """S22: the single halal intercept (§12.4) — scoped index,
    Step-1 unscoped, Step-5 dispatch, chain-mode prefix."""

    HEADER = FULL_HEADER + ["Sub_Category", "Item_Code", "Preferred"]

    def _ws(self):
        rows = [
            self.HEADER,
            # Non-halal meat row: Q in scope, no marker -> INVISIBLE
            # to generic meat queries.
            ["Woolworths Beef Mince", "Meat", "1kg", "$12.00", "", "",
             "", "", "", "", "", "", "", "", "", "",
             "beef mince", "AAA", ""],
            # Halal row via NAME (Col P empty): VISIBLE.
            ["Halal Beef Mince BrandX", "Meat", "500g", "$7.50", "",
             "", "", "", "", "", "", "", "", "", "", "",
             "beef mince", "BBB", ""],
            # Non-scope row: VISIBLE to everything.
            ["Full Cream Milk", "Dairy", "3L", "$3.00", "", "",
             "", "", "", "", "", "", "", "", "", "",
             "", "", ""],
            # Halal row via Col P MARKER: VISIBLE.
            ["Chicken Breast", "Meat", "1kg", "$14.50", "", "",
             "", "", "", "", "", "", "", "", "", "halal",
             "chicken breast", "CCC", ""],
        ]
        return FakeWorksheet(rows)

    def test_meat_query_invisible_to_non_halal_row(self):
        """Generic meat query never resolves the non-halal twin. """""
        engine = LookupEngine(self._ws())
        result = engine.find_product("beef mince", interactive=False)
        self.assertNotEqual(result.generic_name,
                            "Woolworths Beef Mince")

    def test_meat_query_sees_halal_rows_and_non_scope_rows(self):
        """Scoped search resolves the halal twin. """""
        engine = LookupEngine(self._ws())
        result = engine.find_product("beef mince", interactive=False)
        self.assertEqual(result.generic_name,
                         "Halal Beef Mince BrandX")

    def test_full_name_exact_match_still_resolves_non_halal(self):
        """Step 1 is UNSCOPED: a full non-halal name is a database
        query (D-H4). """""
        # The live-fill layer is mocked empty (no network — this file
        # is pure unit tests): a non-interactive resolve of a
        # WW-only row must keep the pure EXACT_SHEET sheet answer
        # instead of drifting into SHEET_AND_LIVE.
        engine = LookupEngine(self._ws())
        with patch.object(LookupEngine, "_live_search_pair",
                          return_value=([], [], "ok")):
            result = engine.find_product("Woolworths Beef Mince",
                                         interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)

    def test_non_meat_query_completely_unscoped(self):
        """Non-meat queries never scope the index. """""
        # Same live-fill mock: the sheet row is WW-only, and the
        # merged SHEET_AND_LIVE tag must not mask the Step-1 hit.
        engine = LookupEngine(self._ws())
        with patch.object(LookupEngine, "_live_search_pair",
                          return_value=([], [], "ok")):
            result = engine.find_product("Full Cream Milk",
                                         interactive=False)
        self.assertEqual(result.status, LookupStatus.EXACT_SHEET)

    def test_step5_meat_query_dispatches_to_chain(self):
        """A meat query with NO scoped sheet hit dispatches to
        core.halal.resolve_halal_item exactly once. """""
        from core.halal import HalalResolution
        ws = FakeWorksheet([self.HEADER, [
            "Full Cream Milk", "Dairy", "3L", "$3.00", "", "",
            "", "", "", "", "", "", "", "", "", "", "", "", ""]])
        sentinel = HalalResolution(tier=3, butcher_line="butcher")
        with patch("core.halal.resolve_halal_item",
                   return_value=sentinel) as rh:
            engine = LookupEngine(ws)
            result = engine.find_product("lamb", interactive=False)
        rh.assert_called_once()
        self.assertIs(result, sentinel)

    def test_chain_mode_live_query_carries_halal_prefix(self):
        """Chain mode injects the halal prefix into the live query."""
        engine = LookupEngine(self._ws())
        with patch.object(LookupEngine, "_live_search_pair",
                          return_value=([], [], "ok")) as lsp:
            engine.find_product("lamb", interactive=False,
                                _halal_chain=True)
        self.assertEqual(lsp.call_args.args[0], "halal lamb")

    def test_scoped_index_drops_only_non_halal_meat_rows(self):
        """The scoped view drops ONLY non-marked auto-scope rows."""
        engine = LookupEngine(self._ws())
        engine._ensure_index()
        scoped = engine._halal_scoped_index()
        names = [d["generic_name"] for d in scoped._rows]
        self.assertNotIn("Woolworths Beef Mince", names)
        self.assertIn("Halal Beef Mince BrandX", names)
        self.assertIn("Full Cream Milk", names)
        self.assertIn("Chicken Breast", names)


if __name__ == "__main__":
    unittest.main()
