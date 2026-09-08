#!/usr/bin/env python3
"""18 pure unit tests for core/sheets_sync and core/schema_upgrade.

No network, no live sheet. Uses FakeWorksheet to simulate gspread.
Usage:
    python grocery-price-tracker/tests/test_sheets_sync.py
"""
from __future__ import annotations

import copy
import re
import sys
import tempfile
import time as time_module
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

# Bootstrap sys.path so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent  # tests/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

import core.item_codes as item_codes

from gspread.exceptions import APIError

from core.schema_upgrade import (
    EXPECTED_BASE_HEADERS,
    NEW_COLUMNS,
    audit_schema,
    upgrade_schema,
)
from core.sheets_sync import (
    sync_prices, update_single_price, _update_with_backoff, _find_col,
    add_product_row, mark_not_available, mark_price_gone,
    set_store_keyword,
)
from core.name_matcher import KeywordIndex, MatchResult
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
    """Parse 'A2:O83' -> (start_row, start_col, end_row, end_col). All 1-based."""
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
        self.added_cols = 0

    def get_all_values(self):
        return [list(r) for r in self._values]

    def row_values(self, n):
        """1-based row read (FIX-9 read-back verify support)."""
        idx = int(n) - 1
        if 0 <= idx < len(self._values):
            return list(self._values[idx])
        return []

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

    def batch_update(self, updates):
        """Record a batch_update call (list of {range, values} dicts)."""
        self.batch_updates = updates

    def add_cols(self, n):
        self.added_cols += n
        for r in self._values:
            r.extend([""] * n)


# ============================================================================
# Test suite
# ============================================================================


class TestSheetsSync(unittest.TestCase):
    """18 pure unit tests for sheets_sync and schema_upgrade."""

    # ------------------------------------------------------------------ #
    # Test 1: sync_prices writes matched rows
    # ------------------------------------------------------------------ #
    def test_sync_prices_writes_matched_rows(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", ""],
            ["Full Cream", "Dairy", "2L", "", "", "", "", "", "", "", "", ""],
            ["Beef Mince", "Meat", "500g", "", "", "", "", "", "", "", "", ""],
            ["Cheese", "Dairy", "500g", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "woolworths",
                        "Oatly Barista 1L", "exact_keyword"),
            MatchResult(True, 4, "Beef Mince", "woolworths",
                        "Woolworths Beef Mince 500g", "exact_keyword"),
        ]
        items = [
            ProductItem("woolworths", "Oatly Barista 1L", 4.50),
            ProductItem("woolworths", "Woolworths Beef Mince 500g", 8.00),
        ]

        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.rows_updated, 2)
        self.assertEqual(report.items_matched, 2)
        self.assertEqual(report.stores_synced, ["woolworths"])
        self.assertEqual(len(ws.updates), 1)

        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], 4.50)   # row 2, col D
        self.assertEqual(updated[3][3], 8.00)   # row 4, col D
        # H timestamp set
        self.assertTrue(updated[1][7])
        self.assertTrue(updated[3][7])

    # ------------------------------------------------------------------ #
    # Test 2: Multi-store same row
    # ------------------------------------------------------------------ #
    def test_sync_prices_multi_store_same_row(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "woolworths",
                        "Oatly Barista 1L", "exact_keyword"),
            MatchResult(True, 2, "Oat Milk", "coles",
                        "Coles Oat Milk 1L", "exact_keyword"),
        ]
        items = [
            ProductItem("woolworths", "Oatly Barista 1L", 4.50),
            ProductItem("coles", "Coles Oat Milk 1L", 4.00),
        ]

        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.rows_updated, 2)
        self.assertEqual(report.items_matched, 2)
        self.assertEqual(sorted(report.stores_synced), ["coles", "woolworths"])

        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], 4.50)  # D = woolworths
        self.assertEqual(updated[1][4], 4.00)  # E = coles
        self.assertTrue(updated[1][7])          # H = timestamp

    # ------------------------------------------------------------------ #
    # Test 3: Skips unmatched items
    # ------------------------------------------------------------------ #
    def test_sync_prices_skips_unmatched(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "woolworths",
                        "Oatly Barista 1L", "exact_keyword"),
            MatchResult(False, None, "", "woolworths",
                        "Unknown Product 999g", "none"),
        ]
        items = [
            ProductItem("woolworths", "Oatly Barista 1L", 4.50),
            ProductItem("woolworths", "Unknown Product 999g", 9.99),
        ]

        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.items_skipped, 1)
        self.assertEqual(report.rows_updated, 1)
        self.assertEqual(report.items_matched, 1)

        # Unmatched row should be untouched
        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], 4.50)  # matched row updated

    # ------------------------------------------------------------------ #
    # Test 4: Dry run writes nothing
    # ------------------------------------------------------------------ #
    def test_sync_prices_dry_run_writes_nothing(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "woolworths",
                        "Oatly Barista 1L", "exact_keyword"),
        ]
        items = [
            ProductItem("woolworths", "Oatly Barista 1L", 4.50),
        ]

        report = sync_prices(results, items, worksheet=ws, dry_run=True)
        self.assertEqual(len(ws.updates), 0)
        self.assertTrue(report.dry_run)
        self.assertEqual(report.range_written, "")

    # ------------------------------------------------------------------ #
    # Test 5: Pads short rows
    # ------------------------------------------------------------------ #
    def test_sync_prices_pads_short_rows(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
            "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        ]
        rows = [
            header,
            ["Oat Milk"],  # very short row
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "woolworths",
                        "Oatly Barista 1L", "exact_keyword"),
        ]
        items = [
            ProductItem("woolworths", "Oatly Barista 1L", 4.50),
        ]

        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.rows_updated, 1)
        self.assertEqual(len(ws.updates), 1)

        # Row should be padded to full width
        updated = ws.get_all_values()
        self.assertEqual(len(updated[1]), 15)

    # ------------------------------------------------------------------ #
    # Test 6: Specials written when is_special
    # ------------------------------------------------------------------ #
    def test_sync_prices_specials_written_when_is_special(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
            "", "", "Coles_Specials",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", "",
             "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "coles",
                        "Coles Oat Milk 1L", "exact_keyword"),
        ]
        items = [
            ProductItem("coles", "Coles Oat Milk 1L", 3.50,
                        is_special=True, special_desc="Half Price"),
        ]

        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.rows_updated, 1)

        updated = ws.get_all_values()
        # Coles_Specials is at index 14 (N) — D25 vocabulary: a flagged
        # item with a non-pattern desc classifies as "discount".
        self.assertEqual(updated[1][14], "discount")

    # ------------------------------------------------------------------ #
    # Test 7: Specials cleared when not special
    # ------------------------------------------------------------------ #
    def test_sync_prices_specials_cleared_when_not_special(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
            "", "", "Coles_Specials",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", "",
             "", "", "Old Special"],
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "coles",
                        "Coles Oat Milk 1L", "exact_keyword"),
        ]
        items = [
            ProductItem("coles", "Coles Oat Milk 1L", 3.50,
                        is_special=False),
        ]

        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.rows_updated, 1)

        updated = ws.get_all_values()
        # Stale specials overwritten with the D25 "no" marker
        self.assertEqual(updated[1][14], "no")

    # ------------------------------------------------------------------ #
    # Test 8: Missing specials columns warns
    # ------------------------------------------------------------------ #
    def test_sync_prices_missing_specials_columns_warns(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "woolworths",
                        "Oatly Barista 1L", "exact_keyword"),
        ]
        items = [
            ProductItem("woolworths", "Oatly Barista 1L", 4.50),
        ]

        report = sync_prices(results, items, worksheet=ws)
        self.assertTrue(len(report.warnings) > 0)
        # Price + timestamp still written
        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], 4.50)
        self.assertTrue(updated[1][7])

    # ------------------------------------------------------------------ #
    # Test 9: Rewards last write wins
    # ------------------------------------------------------------------ #
    def test_sync_prices_rewards_last_write_wins(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
            "", "", "Rewards_Points",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", "",
             "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        results = [
            MatchResult(True, 2, "Oat Milk", "woolworths",
                        "Oatly Barista 1L", "exact_keyword"),
            MatchResult(True, 2, "Oat Milk", "coles",
                        "Coles Oat Milk 1L", "exact_keyword"),
        ]
        items = [
            ProductItem("woolworths", "Oatly Barista 1L", 4.50,
                        rewards_points="100"),
            ProductItem("coles", "Coles Oat Milk 1L", 4.00,
                        rewards_points="200"),
        ]

        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.rows_updated, 2)

        updated = ws.get_all_values()
        # Last store (coles) wins
        self.assertEqual(updated[1][14], "200")

    # ------------------------------------------------------------------ #
    # Test 10: update_single_price found
    # ------------------------------------------------------------------ #
    def test_update_single_price_found(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["", "", "", "", "", "", "", "", "", "", "", ""],
            ["", "", "", "", "", "", "", "", "", "", "", ""],
            ["Oat Milk", "Dairy", "1L", "3.50", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        result = update_single_price(
            "Oat Milk", "woolworths", 4.20, worksheet=ws,
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["row_index"], 4)
        self.assertEqual(result["old_price"], 3.50)
        self.assertEqual(result["new_price"], 4.20)
        self.assertTrue(result["wrote"])
        self.assertTrue(result["range_written"])

        # Verify write applied
        updated = ws.get_all_values()
        self.assertEqual(updated[3][3], 4.20)  # D3
        self.assertTrue(updated[3][7])           # H3 timestamp

    # ------------------------------------------------------------------ #
    # Test 11: update_single_price not found
    # ------------------------------------------------------------------ #
    def test_update_single_price_not_found(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        result = update_single_price(
            "Does Not Exist", "woolworths", 4.20, worksheet=ws,
        )
        self.assertFalse(result["found"])
        self.assertEqual(result["error"], "product not found")
        self.assertFalse(result["wrote"])
        self.assertEqual(len(ws.updates), 0)

    # ------------------------------------------------------------------ #
    # Test 12: update_single_price dry run
    # ------------------------------------------------------------------ #
    def test_update_single_price_dry_run(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "3.50", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        result = update_single_price(
            "Oat Milk", "woolworths", 4.20, worksheet=ws, dry_run=True,
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["old_price"], 3.50)
        self.assertFalse(result["wrote"])
        self.assertEqual(len(ws.updates), 0)

    # ------------------------------------------------------------------ #
    # Test 13: update_single_price invalid store
    # ------------------------------------------------------------------ #
    def test_update_single_price_invalid_store(self):
        ws = FakeWorksheet([["H1"]])
        result = update_single_price(
            "Oat Milk", "iga", 4.20, worksheet=ws,
        )
        self.assertFalse(result["found"])
        self.assertIn("unknown store", result["error"])
        self.assertFalse(result["wrote"])
        self.assertEqual(len(ws.updates), 0)

    # ------------------------------------------------------------------ #
    # Test 14: _update_with_backoff retries on 429
    # ------------------------------------------------------------------ #
    def test_update_with_backoff_retries_on_429(self):
        import core.sheets_sync as ss

        class FakeAPIError(Exception):
            def __init__(self, status):
                self.status = status

        call_count = [0]

        def flaky_update(*, values, range_name):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise FakeAPIError(429)
            # Success on 3rd call

        ws = FakeWorksheet([["H1"]])
        ws.update = flaky_update

        orig_api_error = ss.APIError
        orig_sleep = time_module.sleep
        ss.APIError = FakeAPIError
        time_module.sleep = lambda x: None
        try:
            ss._update_with_backoff(ws, [["x"]], "A1:A1")
            self.assertEqual(call_count[0], 3)
        finally:
            ss.APIError = orig_api_error
            time_module.sleep = orig_sleep

    # ------------------------------------------------------------------ #
    # Test 15: _update_with_backoff reraises non-429
    # ------------------------------------------------------------------ #
    def test_update_with_backoff_reraises_non_429(self):
        import core.sheets_sync as ss

        class FakeAPIError(Exception):
            def __init__(self, status):
                self.status = status

        call_count = [0]

        def failing_update(*, values, range_name):
            call_count[0] += 1
            raise FakeAPIError(500)

        ws = FakeWorksheet([["H1"]])
        ws.update = failing_update

        orig_api_error = ss.APIError
        orig_sleep = time_module.sleep
        ss.APIError = FakeAPIError
        time_module.sleep = lambda x: None
        try:
            with self.assertRaises(FakeAPIError):
                ss._update_with_backoff(ws, [["x"]], "A1:A1")
            self.assertEqual(call_count[0], 1)  # no retry
        finally:
            ss.APIError = orig_api_error
            time_module.sleep = orig_sleep

    # ------------------------------------------------------------------ #
    # Test 16: Schema audit detects missing new columns
    # ------------------------------------------------------------------ #
    def test_audit_schema_detects_missing_new_columns(self):
        header = EXPECTED_BASE_HEADERS[:]  # only base 9 columns
        ws = FakeWorksheet([header, ["row1"] * 9])

        report = audit_schema(worksheet=ws)
        self.assertEqual(report["missing_new"], NEW_COLUMNS)
        self.assertTrue(report["needs_upgrade"])
        self.assertEqual(report["col_count"], 9)

    # ------------------------------------------------------------------ #
    # Test 17: Schema upgrade idempotent
    # ------------------------------------------------------------------ #
    def test_upgrade_schema_idempotent(self):
        header = EXPECTED_BASE_HEADERS[:]
        ws = FakeWorksheet([header, ["row1"] * 9])

        # First run: should add columns
        report1 = upgrade_schema(worksheet=ws)
        self.assertTrue(report1["wrote"])
        self.assertEqual(report1["added_columns"], NEW_COLUMNS)

        # Second run: idempotent
        report2 = upgrade_schema(worksheet=ws)
        self.assertFalse(report2["wrote"])
        self.assertEqual(report2["added_columns"], [])

        # Verify columns were added
        audit = audit_schema(worksheet=ws)
        self.assertEqual(audit["existing_new"], NEW_COLUMNS)
        self.assertEqual(audit["col_count"], 9 + len(NEW_COLUMNS))

    # ------------------------------------------------------------------ #
    # Test 18: Normalize consistency between modules
    # ------------------------------------------------------------------ #
    def test_normalize_consistent_between_modules(self):
        # KeywordIndex._normalize is the canonical normalizer
        normalized = KeywordIndex._normalize("  Oat   Milk  ")
        self.assertEqual(normalized, "oat milk")

        # _find_col uses the same normalize logic for header matching
        header = ["Product_Name", "  Coles_Specials  "]
        idx = _find_col(header, "coles specials")
        self.assertEqual(idx, 1)

    # ------------------------------------------------------------------ #
    # Test 19: update_single_price matches via Col I keyword (DEFECT-1)
    # ------------------------------------------------------------------ #
    def test_update_single_price_matches_via_store_keyword(self):
        """Col A differs but Col I (Woolworths keyword) matches -> found."""
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Generic Milk", "Dairy", "2L", "", "", "", "", "",
             "Woolworths Full Cream 2L", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        result = update_single_price(
            "Woolworths Full Cream 2L", "woolworths", 3.50, worksheet=ws,
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["row_index"], 2)
        self.assertEqual(result["new_price"], 3.50)

    # ------------------------------------------------------------------ #
    # Test 20: update_single_price Col A wins over keyword
    # ------------------------------------------------------------------ #
    def test_update_single_price_col_a_wins_over_keyword(self):
        """Col A match takes priority even when keyword also matches."""
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Full Cream Milk", "Dairy", "2L", "4.00", "", "", "", "",
             "", "", "", ""],
            ["Generic Milk", "Dairy", "1L", "2.00", "", "", "", "",
             "Full Cream Milk", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        result = update_single_price(
            "Full Cream Milk", "woolworths", 3.50, worksheet=ws,
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["row_index"], 2)  # Col A match wins
        self.assertEqual(result["old_price"], 4.00)

    # ------------------------------------------------------------------ #
    # Test 21: add_product_row appends correctly
    # ------------------------------------------------------------------ #
    def test_add_product_row_appends_correctly(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
            "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
            "Keywords",
        ]
        rows = [header]
        ws = FakeWorksheet(rows)

        result = add_product_row(
            generic_name="Test Milk 2L",
            store="woolworths",
            price=3.50,
            brand="TestBrand",
            size="2L",
            category="Dairy",
            store_keyword="Woolworths Test Milk 2L",
            alias="test milk",
            worksheet=ws,
        )
        self.assertTrue(result["wrote"])
        self.assertEqual(result["row_index"], 2)  # first data row

        updated = ws.get_all_values()
        self.assertEqual(updated[1][0], "Test Milk 2L")     # Col A
        self.assertEqual(updated[1][1], "Dairy")             # Col B
        self.assertEqual(updated[1][2], "2L")                # Col C
        self.assertEqual(updated[1][3], 3.50)                # Col D RAW
        self.assertEqual(updated[1][6], "TestBrand")         # Col G
        self.assertTrue(updated[1][7])                        # Col H
        self.assertEqual(updated[1][8], "Woolworths Test Milk 2L")  # Col I
        self.assertEqual(updated[1][15], "test milk")         # Col P

    def test_add_product_row_writes_home_literal(self):
        """Home-brand rows get the literal 'Home' marker in Col G;
        the price cell still stores the RAW value."""
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        ws = FakeWorksheet([header])

        result = add_product_row(
            generic_name="Macro Wholefoods Market Oats 1kg",
            store="woolworths",
            price=6.20,
            brand="Macro Wholefoods Market",
            size="1kg",
            worksheet=ws,
        )
        self.assertTrue(result["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][6], "Home")   # Col G literal marker
        self.assertEqual(updated[1][3], 6.20)     # Col D stays RAW

    def test_add_product_row_home_via_name_fallback(self):
        """Empty brand + leading home-brand label in name -> 'Home'."""
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        ws = FakeWorksheet([header])

        result = add_product_row(
            generic_name="Essentials Milk 2L",
            store="woolworths",
            price=3.10,
            brand="",
            size="2L",
            worksheet=ws,
        )
        self.assertTrue(result["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][6], "Home")   # via name fallback
        self.assertEqual(updated[1][3], 3.10)     # price stays raw

    # ------------------------------------------------------------------ #
    # Test 22: add_product_row dry run
    # ------------------------------------------------------------------ #
    def test_add_product_row_dry_run(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [header, ["Milk", "", "", "3.00", "", "", "", "", "", "", "", ""]]
        ws = FakeWorksheet(rows)

        result = add_product_row(
            generic_name="New Item", store="coles", price=5.00,
            size="500g", dry_run=True, worksheet=ws,
        )
        self.assertFalse(result["wrote"])
        self.assertEqual(result["row_index"], 3)  # would be row 3
        self.assertEqual(len(ws.updates), 0)

    # ------------------------------------------------------------------ #
    # Test 23: add_product_row validation failures
    # ------------------------------------------------------------------ #
    def test_add_product_row_validation_failures(self):
        ws = FakeWorksheet([["H1"]])

        # Unknown store (B1: size arg now REQUIRED at call sites)
        r1 = add_product_row("Milk", "iga", 4.00, size="1L", worksheet=ws)
        self.assertFalse(r1["wrote"])
        self.assertIn("unknown store", r1["error"])

        # Empty name
        r2 = add_product_row("", "woolworths", 4.00, size="1L",
                             worksheet=ws)
        self.assertFalse(r2["wrote"])
        self.assertIn("generic_name", r2["error"])

        # Price <= 0
        r3 = add_product_row("Milk", "woolworths", 0, size="1L",
                             worksheet=ws)
        self.assertFalse(r3["wrote"])
        self.assertIn("price", r3["error"])

    # ------------------------------------------------------------------ #
    # Test 24: mark_not_available writes NA to keyword + price
    # ------------------------------------------------------------------ #
    def test_mark_not_available_writes_na(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        result = mark_not_available("Oat Milk", "woolworths", worksheet=ws)
        self.assertTrue(result["found"])
        self.assertTrue(result["wrote"])

        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], "NA")   # Col D = "NA"
        self.assertEqual(updated[1][8], "NA")   # Col I = "NA"

    # ------------------------------------------------------------------ #
    # Test 25: mark_not_available product not found
    # ------------------------------------------------------------------ #
    def test_mark_not_available_not_found(self):
        ws = FakeWorksheet([["H1"]])
        result = mark_not_available("Nonexistent", "coles", worksheet=ws)
        self.assertFalse(result["found"])
        self.assertIn("product not found", result["error"])

    # ------------------------------------------------------------------ #
    # Test 25b: mark_price_gone writes GONE to price col ONLY
    # (user rule 2026-09-03: keyword col untouched)
    # ------------------------------------------------------------------ #
    def test_mark_price_gone_writes_price_cell_only(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "3.50", "", "", "", "",
             "WW Oat Milk 1L", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        result = mark_price_gone("Oat Milk", "woolworths", worksheet=ws)
        self.assertTrue(result["found"])
        self.assertTrue(result["wrote"])

        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], "GONE")  # Col D = GONE
        # Keyword col (I) must be LEFT ALONE — the whole point.
        self.assertEqual(updated[1][8], "WW Oat Milk 1L")
        # No marker bleed into other cells.
        self.assertEqual(updated[1][4], "")

    def test_mark_price_gone_product_not_found(self):
        ws = FakeWorksheet([["H1"]])
        result = mark_price_gone("Nonexistent", "coles", worksheet=ws)
        self.assertFalse(result["found"])
        self.assertIn("product not found", result["error"])

    def test_mark_price_gone_unknown_store(self):
        result = mark_price_gone("Oat Milk", "aldi")
        self.assertFalse(result["found"])
        self.assertIn("unknown store", result["error"])

    # ------------------------------------------------------------------ #
    # Test 26: set_store_keyword writes keyword to Col I
    # ------------------------------------------------------------------ #
    def test_set_store_keyword_writes_to_col_i(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
        ]
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        result = set_store_keyword(
            "Oat Milk", "woolworths", "WW Oat Milk 1L", worksheet=ws,
        )
        self.assertTrue(result["found"])
        self.assertTrue(result["wrote"])

        updated = ws.get_all_values()
        self.assertEqual(updated[1][8], "WW Oat Milk 1L")  # Col I

    # ------------------------------------------------------------------ #
    # Test 27: set_store_keyword not found
    # ------------------------------------------------------------------ #
    def test_set_store_keyword_not_found(self):
        ws = FakeWorksheet([["H1"]])
        result = set_store_keyword(
            "Nonexistent", "coles", "Coles Item", worksheet=ws,
        )
        self.assertFalse(result["found"])
        self.assertIn("product not found", result["error"])


class TestSpecialsFlagWrites(unittest.TestCase):
    """D25/WP3: M/N cells hold exactly no/discount/multi-buy."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
    ]

    # sync_prices ------------------------------------------------------- #

    def test_sync_prices_writes_multi_buy_and_no(self):
        rows = [
            self.HEADER,
            ["Oat Milk", "Dairy", "1L", "", "", "", "", "", "", "", "",
             "", "", "", ""],
            ["Full Cream", "Dairy", "2L", "", "", "", "", "", "", "", "",
             "", "", "", ""],
            ["Cheese", "Dairy", "500g", "", "", "", "", "", "", "", "",
             "", "", "50% off", ""],
        ]
        ws = FakeWorksheet(rows)
        results = [
            MatchResult(True, 2, "Oat Milk", "coles",
                        "Coles Oat Milk 1L", "exact_keyword"),
            MatchResult(True, 3, "Full Cream", "coles",
                        "Coles Full Cream 2L", "exact_keyword"),
            MatchResult(False, None, "", "coles",
                        "Coles Cheese 500g", "none"),
        ]
        items = [
            ProductItem("coles", "Coles Oat Milk 1L", 3.50,
                        is_special=True, special_desc="Any 2 | $9"),
            ProductItem("coles", "Coles Full Cream 2L", 4.20,
                        is_special=False),
            ProductItem("coles", "Coles Cheese 500g", 5.00,
                        is_special=True, special_desc="Half Price"),
        ]
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.items_matched, 2)
        self.assertEqual(report.items_skipped, 1)
        updated = ws.get_all_values()
        # USER REVISION 2026-09-05 (D-MB3 retired): "Any 2 | $9" is a
        # rate-eligible deal — encoded terms + per-unit deal price.
        self.assertEqual(updated[1][13], "multi-buy 2/$9.00")
        self.assertEqual(updated[1][4], 4.5)    # 9.00 / 2 deal rate
        self.assertEqual(updated[2][13], "no")  # N: not special
        self.assertEqual(updated[3][13], "50% off")  # unmatched: kept

    # add_product_row --------------------------------------------------- #

    def test_add_product_row_default_writes_no(self):
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row(
            "New Milk", "woolworths", 2.50, size="1L", worksheet=ws)
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][12], "no")          # M

    def test_add_product_row_special_writes_discount(self):
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row(
            "New Bread", "coles", 2.00, size="650g", worksheet=ws,
            is_special=True, special_desc="Was $2.00")
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][13], "discount")    # N

    def test_add_product_row_without_specials_cols_no_crash(self):
        header = self.HEADER[:12]
        ws = FakeWorksheet([header])
        res = add_product_row(
            "New Eggs", "woolworths", 4.00, size="700g", worksheet=ws,
            is_special=True, special_desc="Was $5.00")
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(len(updated[1]), len(header))  # nothing added

    # update_single_price ----------------------------------------------- #

    def _ws(self):
        return FakeWorksheet([
            self.HEADER,
            ["Oat Milk", "Dairy", "1L", "$3.00", "", "", "", "2026-01-01",
             "", "", "", "", "", "Old Special", ""],
        ])

    def test_update_single_price_no_special_args_leaves_cell(self):
        ws = self._ws()
        res = update_single_price("Oat Milk", "coles", 3.50, worksheet=ws)
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][13], "Old Special")  # untouched
        self.assertEqual(res["range_written"], "A2:H2")  # no M/N widening

    def test_update_single_price_false_writes_no_and_widens(self):
        ws = self._ws()
        res = update_single_price(
            "Oat Milk", "coles", 3.50, worksheet=ws, is_special=False)
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][13], "no")
        self.assertEqual(res["range_written"], "A2:N2")

    def test_update_single_price_multi_buy(self):
        # §7.2 (2026-09-04): product-specific FOR promos encode their
        # terms into the M/N cell ("multi-buy 2/$4.00").
        ws = self._ws()
        res = update_single_price(
            "Oat Milk", "coles", 3.50, worksheet=ws,
            is_special=True, special_desc="2 for $4")
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][13], "multi-buy 2/$4.00")


class TestAddProductRowRequiredSize(unittest.TestCase):
    """B1: empty size is rejected; marker is accepted (fail-fast)."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
    ]

    def test_blank_size_rejected_with_exact_error(self):
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row("Milk", "coles", 3.0, size="   ",
                              worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertEqual(
            res["error"], "unit is required: pass a size or the marker")
        self.assertEqual(len(ws.updates), 0)  # nothing written

    def test_marker_accepted_and_written_to_col_c(self):
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row("Milk", "coles", 3.0,
                              size="unit unavailable", worksheet=ws)
        self.assertTrue(res["wrote"])
        written = ws.updates[0][0][0]
        self.assertEqual(written[2], "unit unavailable")

    def test_real_size_written_to_col_c(self):
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row("Milk", "coles", 3.0, size="1L",
                              worksheet=ws)
        self.assertTrue(res["wrote"])
        written = ws.updates[0][0][0]
        self.assertEqual(written[2], "1L")


class TestAddProductRowDuplicateGuard(unittest.TestCase):
    """2026-09-01 incident: exact Col A match must not append a dup row."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def _ws_with_milk(self):
        rows = [
            self.HEADER,
            ["Woolworths Full Cream Milk 3L", "Dairy", "3L", "4.30",
             "", "", "Home", "", "milk 3l", "", "", "", "", "", ""],
        ]
        return FakeWorksheet(rows)

    def test_exact_existing_name_refused(self):
        from core.sheets_sync import add_product_row
        ws = self._ws_with_milk()
        res = add_product_row(
            "Woolworths Full Cream Milk 3L", "woolworths", 4.30,
            brand="Woolworths", size="3L", worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertEqual(res["row_index"], 2)
        self.assertIn("already tracked", res["error"])
        self.assertEqual(len(ws.updates), 0)  # nothing appended

    def test_case_variant_merges_per_fix10(self):
        """FIX-10 (D17): exact means EXACT (case-preserved) — a
        lowercase/whitespace variant is NOT exact, so it MERGES via
        the one-line rule (price updated) instead of the dead-end
        refusal."""
        from core.sheets_sync import add_product_row
        ws = self._ws_with_milk()
        res = add_product_row(
            "  woolworths   FULL cream milk 3l ", "woolworths", 4.30,
            brand="Woolworths", size="3L", worksheet=ws)
        self.assertTrue(res["merged"])
        self.assertEqual(res.get("existing_name"),
                         "Woolworths Full Cream Milk 3L")

    def test_new_name_still_appends(self):
        from core.sheets_sync import add_product_row
        ws = self._ws_with_milk()
        res = add_product_row(
            "A2 Full Cream Milk 3L", "woolworths", 4.10,
            brand="A2", size="3L", worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertEqual(res["row_index"], 3)


class TestAddProductRowOneLineRule(unittest.TestCase):
    """2026-09-02 user rule: 1 line per product even when names differ
    slightly; --allow-duplicate is the explicit 2-different-items override."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def _ws_with_hommus(self):
        rows = [
            self.HEADER,
            ["Obela Classic Hommus 200g", "Dairy", "200g", "4.50",
             "", "", "Obela", "", "obela hommus", "", "", "", "", "",
             "", "hommus"],
        ]
        return FakeWorksheet(rows)

    def test_similar_name_merges_into_existing_row(self):
        """Word order + store prefix differ -> ONE row, price updated."""
        from core.sheets_sync import add_product_row
        ws = self._ws_with_hommus()
        res = add_product_row(
            "Woolworths Hommus Classic Obela 200g", "woolworths", 4.20,
            brand="Obela", size="200g", alias="hommus dip",
            worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertTrue(res["merged"])
        self.assertEqual(res["row_index"], 2)
        self.assertEqual(res["existing_name"], "Obela Classic Hommus 200g")
        # No second row appended.
        self.assertEqual(len(ws.get_all_values()), 2)
        # Price updated on the existing row (Col D).
        updated = ws.get_all_values()
        self.assertEqual(float(updated[1][3]), 4.20)

    def test_merge_appends_alias_to_col_p(self):
        from core.sheets_sync import add_product_row
        ws = self._ws_with_hommus()
        res = add_product_row(
            "Obela Hommus Classic 200g", "woolworths", 4.20,
            brand="Obela", size="200g", alias="hommus dip",
            worksheet=ws)
        self.assertTrue(res["merged"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][15], "hommus|hommus dip")

    def test_merge_alias_already_present_not_duplicated(self):
        from core.sheets_sync import add_product_row
        ws = self._ws_with_hommus()
        res = add_product_row(
            "Obela Hommus Classic 200g", "woolworths", 4.20,
            brand="Obela", size="200g", alias="hommus",
            worksheet=ws)
        self.assertTrue(res["merged"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][15], "hommus")

    def test_allow_duplicate_creates_separate_row(self):
        from core.sheets_sync import add_product_row
        ws = self._ws_with_hommus()
        res = add_product_row(
            "Obela Hommus Classic 200g", "woolworths", 4.20,
            brand="Obela", size="200g", allow_duplicate=True,
            worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertFalse(res.get("merged"))
        self.assertEqual(res["row_index"], 3)

    def test_exact_duplicate_refused_even_with_allow_duplicate(self):
        from core.sheets_sync import add_product_row
        ws = self._ws_with_hommus()
        res = add_product_row(
            "Obela Classic Hommus 200g", "woolworths", 4.20,
            brand="Obela", size="200g", allow_duplicate=True,
            worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertIn("already tracked", res["error"])

    def test_different_size_stays_separate_without_override(self):
        """200g vs 400g are different products (token sets differ)."""
        from core.sheets_sync import add_product_row
        ws = self._ws_with_hommus()
        res = add_product_row(
            "Obela Classic Hommus 400g", "woolworths", 7.00,
            brand="Obela", size="400g", worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertFalse(res.get("merged"))
        self.assertEqual(res["row_index"], 3)


class TestNameSimilarityHelpers(unittest.TestCase):
    """token_set_ratio / similarity_tokens — the one-line-rule engine."""

    def test_store_words_ignored(self):
        from core.name_matcher import token_set_ratio
        self.assertEqual(
            token_set_ratio("Woolworths Full Cream Milk 3L",
                            "Full Cream Milk 3l"), 1.0)

    def test_word_order_irrelevant(self):
        from core.name_matcher import token_set_ratio
        self.assertEqual(
            token_set_ratio("Obela Classic Hommus 200g",
                            "Hommus Classic Obela 200g"), 1.0)

    def test_punctuation_ignored(self):
        from core.name_matcher import token_set_ratio
        self.assertEqual(
            token_set_ratio("Carman's Apple & Blueberry",
                            "carmans apple blueberry"), 1.0)

    def test_different_sizes_score_low(self):
        from core.name_matcher import token_set_ratio
        ratio = token_set_ratio("Fruit Straps 5 pack", "Fruit Straps 70g")
        self.assertLess(ratio, 0.8)

    def test_blank_scores_zero(self):
        from core.name_matcher import token_set_ratio
        self.assertEqual(token_set_ratio("", "Milk"), 0.0)


class TestIsSameProduct(unittest.TestCase):
    """The one-line rule engine: same product = one line ALWAYS, unless
    it's the same unit with a different amount (2026-09-02 user rule)."""

    def test_pack_vs_weight_wording_is_same_product(self):
        """WW '5 pack' vs Coles '70G' of the same item -> ONE line."""
        from core.name_matcher import is_same_product
        self.assertTrue(is_same_product(
            "Carman's Apple & Blueberry Fruit Straps 5 pack",
            "CARMANS FRUIT STRAPS APPLE & BLUEBERRY 70G"))

    def test_same_unit_different_amount_is_different(self):
        from core.name_matcher import is_same_product
        self.assertFalse(is_same_product(
            "Obela Classic Hommus 200g", "Obela Classic Hommus 400g"))
        self.assertFalse(is_same_product(
            "Full Cream Milk 1L", "Full Cream Milk 2L"))

    def test_within_20pct_size_variance_still_matches(self):
        """33g (Woolworths) vs 35g (Coles) = 6% apart — the built-in
        20% tolerance keeps them ONE line (user-confirmed 2026-09-02)."""
        from core.name_matcher import is_same_product
        self.assertTrue(is_same_product(
            "Obela Classic Hommus 33g", "Obela Classic Hommus 35g"))
        # ...but 20%+ apart stays separate (200g vs 400g).

    def test_same_size_same_product(self):
        from core.name_matcher import is_same_product
        self.assertTrue(is_same_product(
            "Obela Classic Hommus 200g", "Obela Hommus Classic 200g"))

    def test_brand_words_still_separate(self):
        from core.name_matcher import is_same_product
        self.assertFalse(is_same_product(
            "A2 Full Cream Milk 3L", "Woolworths Full Cream Milk 3L"))

    def test_one_side_missing_size_merges(self):
        from core.name_matcher import is_same_product
        self.assertTrue(is_same_product(
            "Yumi's Herb Falafel 200g", "Yumi's Herb Falafel"))

    def test_blank_is_not_same(self):
        from core.name_matcher import is_same_product
        self.assertFalse(is_same_product("", "Milk 3L"))

    def test_different_families_merge_per_user_rule(self):
        """g vs mL (different unit types) is NOT a keep-apart reason —
        only same-unit-different-amount keeps lines apart."""
        from core.name_matcher import is_same_product
        self.assertTrue(is_same_product(
            "Store Stock Concentrate 500g", "Store Stock Concentrate 500mL"))


class TestAddProductRowPackVsWeight(unittest.TestCase):
    """The 2026-09-01 Carman's incident: WW 5-pack add vs the Coles 70G
    row must fold into ONE line (same product, different pack wording)."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def test_carmans_pack_add_merges_into_weight_row(self):
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([
            self.HEADER,
            ["CARMANS FRUIT STRAPS APPLE & BLUEBERRY 70G", "Snacks",
             "70g", "", "4.50", "", "Carman's", "", "", "carmans straps",
             "", "", "", "", "", ""],
        ])
        res = add_product_row(
            "Carman's Apple & Blueberry Fruit Straps 5 pack",
            "woolworths", 4.50, brand="Carman's", size="5 pack",
            worksheet=ws)
        self.assertTrue(res["merged"])
        self.assertEqual(res["row_index"], 2)
        # One row, WW price now filled on the existing line.
        updated = ws.get_all_values()
        self.assertEqual(len(updated), 2)
        self.assertEqual(float(updated[1][3]), 4.50)


class TestSyncOverwriteSemantics(unittest.TestCase):
    """2026-09-02: every sync OVERWRITES all prices — mapped rows
    absent from the list get 'N/A <date>' (stale prices never linger),
    listed-but-priceless items get 'unavailable <date>'; the date
    anchors no-price week aging and survives until a real price
    returns. Rows with blank or literal-NA keywords are never marked;
    a store whose list wasn't provided is never marked either."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
    ]

    def _ws(self, *data_rows):
        return FakeWorksheet([self.HEADER] + [list(r) for r in data_rows])

    def _matched(self, ws_row, store, price, name="Item"):
        result = MatchResult(True, ws_row, name, store, name,
                             "exact_keyword")
        item = ProductItem(store, name, price)
        return [result], [item]

    def test_notfound_mapped_row_marked_na_with_date(self):
        ws = self._ws(
            ["Gone Product", "", "", "5.50", "", "", "", "",
             "gone product", "", "", ""],
            ["Other", "", "", "", "", "", "", "",
             "other", "", "", ""],
        )
        # One DIFFERENT woolworths item matches (row 3) — the store
        # list was provided, so the absent row 2 must be marked.
        results, items = self._matched(3, "woolworths", 3.0, "Other")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.notfound_written, 1)
        self.assertIn("Gone Product", report.notfound_items)
        updated = ws.get_all_values()
        self.assertRegex(updated[1][3], r"^N/A \d{4}-\d{2}-\d{2}$")
        self.assertEqual(float(updated[2][3]), 3.0)

    def test_stale_price_replaced_by_na(self):
        """The headline fix: price lingers after the item left the
        list — the sync must overwrite it with the N/A marker."""
        ws = self._ws(
            ["Old Fav", "", "", "5.50", "", "", "", "",
             "old fav", "old fav coles", "", ""],
            ["Still Here", "", "", "", "", "", "", "",
             "still here", "", "", ""],
        )
        results, items = self._matched(3, "woolworths", 2.0, "Still Here")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.notfound_written, 1)
        updated = ws.get_all_values()
        self.assertRegex(updated[1][3], r"^N/A \d{4}-\d{2}-\d{2}$")

    def test_listed_but_no_price_marked_unavailable(self):
        ws = self._ws(
            ["Stock Item", "", "", "4.00", "", "", "", "",
             "stock item", "", "", ""],
        )
        results, items = self._matched(2, "woolworths", 0, "Stock Item")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.unavailable_written, 1)
        updated = ws.get_all_values()
        self.assertRegex(updated[1][3], r"^unavailable \d{4}-\d{2}-\d{2}$")

    def test_found_row_with_price_not_marked(self):
        ws = self._ws(
            ["Priced", "", "", "", "", "", "", "",
             "priced", "", "", ""],
        )
        results, items = self._matched(2, "woolworths", 4.5, "Priced")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.notfound_written, 0)
        self.assertEqual(report.unavailable_written, 0)
        self.assertEqual(ws.get_all_values()[1][3], 4.5)

    def test_blank_and_na_keyword_rows_never_marked(self):
        ws = self._ws(
            ["No Kw", "", "", "1.00", "", "", "", "", "", "", "", ""],
            ["Deliberate", "", "", "2.00", "", "", "", "",
             "NA", "NA", "", ""],
            ["Other", "", "", "", "", "", "", "",
             "other", "", "", ""],
        )
        results, items = self._matched(4, "woolworths", 3.0, "Other")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.notfound_written, 0)
        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], "1.00")   # blank kw untouched
        self.assertEqual(updated[2][3], "2.00")   # NA kw untouched

    def test_store_not_provided_no_marking(self):
        """Coles list failed to parse (no coles items) — mapped Coles
        rows must keep their prices; only a warning is added."""
        ws = self._ws(
            ["Coles Only", "", "", "", "3.00", "", "", "",
             "", "coles only", "", ""],
        )
        results, items = self._matched(2, "woolworths", 1.5, "Other")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.notfound_written, 0)
        self.assertEqual(ws.get_all_values()[1][4], "3.00")
        self.assertTrue(any("coles list not provided" in w
                            for w in report.warnings))

    def test_marker_anchor_date_preserved(self):
        """An already-marked row keeps its original anchor — the week
        count grows, it never resets while the item stays price-less."""
        ws = self._ws(
            ["Long Gone", "", "", "N/A 2026-08-01", "", "", "", "",
             "long gone", "", "", ""],
            ["Other", "", "", "", "", "", "", "",
             "other", "", "", ""],
        )
        results, items = self._matched(3, "woolworths", 3.0, "Other")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.notfound_written, 0)  # no rewrite
        self.assertEqual(ws.get_all_values()[1][3], "N/A 2026-08-01")

    def test_returning_price_overwrites_marker(self):
        ws = self._ws(
            ["Back Again", "", "", "N/A 2026-08-01", "", "", "", "",
             "back again", "", "", ""],
        )
        results, items = self._matched(2, "woolworths", 6.25, "Back Again")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(ws.get_all_values()[1][3], 6.25)

    def test_one_store_na_other_priced_is_not_reported(self):
        """WW drops the item (N/A) but Coles still prices it — the
        overwrite happens; no-price surfacing (both stores price-less)
        is the CLI's job. Both store lists provided this run."""
        ws = self._ws(
            ["Split Item", "", "", "4.00", "4.20", "", "", "",
             "split item", "split item", "", ""],
            ["WW Only", "", "", "", "", "", "", "",
             "ww only", "", "", ""],
        )
        results = [
            MatchResult(True, 2, "Split Item", "coles",
                        "Split Item", "exact_keyword"),
            MatchResult(True, 3, "WW Only", "woolworths",
                        "WW Only", "exact_keyword"),
        ]
        items = [
            ProductItem("coles", "Split Item", 4.20),
            ProductItem("woolworths", "WW Only", 2.00),
        ]
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.notfound_written, 1)
        updated = ws.get_all_values()
        self.assertRegex(updated[1][3], r"^N/A \d{4}-\d{2}-\d{2}$")
        self.assertEqual(float(updated[1][4]), 4.20)

    def test_specials_invariant_absent_row_normalized_to_no(self):
        """D25 (2026-09-02): an absent-from-list row's stale 'discount'
        flag clears to 'no' — absence = not on special."""
        ws = self._ws(
            ["Gone Product", "", "", "5.50", "", "", "", "",
             "gone product", "", "", "", "discount", ""],
            ["Other", "", "", "", "", "", "", "",
             "other", "", "", "", "", ""],
        )
        results, items = self._matched(3, "woolworths", 3.0, "Other")
        sync_prices(results, items, worksheet=ws)
        updated = ws.get_all_values()
        self.assertEqual(updated[1][12], "no")
        self.assertRegex(updated[1][3], r"^N/A \d{4}-\d{2}-\d{2}$")

    def test_specials_invariant_na_keyword_blank_filled(self):
        """Deliberately-NA rows normalize blank specials to 'no' once."""
        ws = self._ws(
            ["Never Stocked", "", "", "2.00", "", "", "", "",
             "NA", "NA", "", "", "", ""],
            ["Other", "", "", "", "", "", "", "",
             "other", "", "", "", "", ""],
        )
        results, items = self._matched(3, "woolworths", 3.0, "Other")
        report = sync_prices(results, items, worksheet=ws)
        self.assertEqual(report.notfound_written, 0)  # NA never marked
        updated = ws.get_all_values()
        self.assertEqual(updated[1][12], "no")
        self.assertEqual(updated[1][3], "2.00")  # price untouched

    def test_specials_invariant_seen_row_keeps_fresh_value(self):
        """Matched rows keep the value the match loop just classified
        (multi-buy stays multi-buy with encoded terms; the pass never
        overwrites them)."""
        ws = self._ws(
            ["Listed Item", "", "", "", "", "", "", "",
             "listed item", "", "", "", "", ""],
        )
        results = [MatchResult(True, 2, "Listed Item", "woolworths",
                               "Listed Item", "exact_keyword")]
        items = [ProductItem("woolworths", "Listed Item", 4.0,
                             is_special=True, special_desc="2 for $4.50")]
        sync_prices(results, items, worksheet=ws)
        updated = ws.get_all_values()
        self.assertEqual(updated[1][12], "multi-buy 2/$4.50")


class TestUpdateSinglePriceBackfill(unittest.TestCase):
    """C.1: blank Col C healed in the same write; never overwritten."""

    def test_blank_col_c_backfilled_once_from_explicit_size(self):
        ws = FakeWorksheet([
            ["Name", "Cat", "Size", "WW", "Coles", "", "Brand", "TS"],
            ["Milk", "", "", "", "", "", "", ""],
        ])
        from core.sheets_sync import update_single_price
        res = update_single_price("Milk", "coles", 3.0,
                                  size="1L", worksheet=ws)
        self.assertTrue(res["wrote"])
        row = ws.updates[0][0][0]
        self.assertEqual(row[2], "1L")

    def test_second_run_writes_nothing_new_to_col_c(self):
        ws = FakeWorksheet([
            ["Name", "Cat", "Size", "WW", "Coles", "", "Brand", "TS"],
            ["Milk", "", "1L", "", "", "", "", ""],
        ])
        from core.sheets_sync import update_single_price
        update_single_price("Milk", "coles", 3.5,
                            size="unit unavailable", worksheet=ws)
        row = ws.updates[0][0][0]
        self.assertEqual(row[2], "1L")  # non-empty Col C untouched

    def test_name_parse_backfills_when_no_size_param(self):
        ws = FakeWorksheet([
            ["Name", "Cat", "Size", "WW", "Coles", "", "Brand", "TS"],
            ["Milk 2L", "", "", "", "", "", "", ""],
        ])
        from core.sheets_sync import update_single_price
        update_single_price("Milk 2L", "coles", 3.0, worksheet=ws)
        self.assertEqual(ws.updates[0][0][0][2], "2L")


class TestSyncPricesColCHeal(unittest.TestCase):
    """B7/C.1: sync heals blank Col C; never overwrites, no marker."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
    ]

    def _run(self, ws, item, result):
        from core.sheets_sync import sync_prices
        return sync_prices([result], [item], worksheet=ws)

    def test_blank_col_c_healed_from_item_size(self):
        ws = FakeWorksheet([
            self.HEADER,
            ["Milk", "", "", "", "", "", "", "", "", "", "", "",
             "", "", ""],
        ])
        result = MatchResult(True, 2, "Milk", "coles",
                             "Coles Milk 600g", "exact_keyword")
        item = ProductItem("coles", "Coles Milk 600g", 3.0, size="600g")
        self._run(ws, item, result)
        row = ws.updates[0][0][0]
        self.assertEqual(row[2], "600g")

    def test_blank_col_c_healed_from_raw_name_parse(self):
        ws = FakeWorksheet([
            self.HEADER,
            ["Bread", "", "", "", "", "", "", "", "", "", "", "",
             "", "", ""],
        ])
        result = MatchResult(True, 2, "Bread", "coles",
                             "Coles Bread 650g", "exact_keyword")
        item = ProductItem("coles", "Coles Bread 650g", 2.5)
        self._run(ws, item, result)
        row = ws.updates[0][0][0]
        self.assertEqual(row[2], "650g")

    def test_nonempty_col_c_untouched_and_no_marker_written(self):
        # Case 1: item size "2L" must NOT overwrite Col C "1L".
        ws = FakeWorksheet([
            self.HEADER,
            ["Milk", "", "1L", "", "", "", "", "", "", "", "", "",
             "", "", ""],
        ])
        result = MatchResult(True, 2, "Milk", "coles",
                             "Coles Milk 2L", "exact_keyword")
        item = ProductItem("coles", "Coles Milk 2L", 3.0, size="2L")
        self._run(ws, item, result)
        row = ws.updates[0][0][0]
        self.assertEqual(row[2], "1L")

        # Case 2: unparseable item (no size, no size in raw_name) ->
        # Col C stays "" (no marker ever guessed, D-U3).
        ws2 = FakeWorksheet([
            self.HEADER,
            ["Herbs", "", "", "", "", "", "", "", "", "", "", "",
             "", "", ""],
        ])
        result2 = MatchResult(True, 2, "Herbs", "coles",
                              "Coles Herbs", "exact_keyword")
        item2 = ProductItem("coles", "Coles Herbs", 2.0)
        self._run(ws2, item2, result2)
        row2 = ws2.updates[0][0][0]
        self.assertEqual(row2[2], "")


class TestAddProductRowQRS(unittest.TestCase):
    """Q/R/S wiring on add_product_row (spec §5 + plan §S9, §13.6)."""

    HEADER_A_S = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
        "Sub_Category", "Item_Code", "Preferred",
    ]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_path = Path(self._tmp.name)
        reg_patch = mock.patch.object(
            item_codes, "REGISTRY_PATH", tmp_path / "registry.json")
        lock_patch = mock.patch.object(
            item_codes, "LOCK_PATH", tmp_path / ".item_code_lock")
        reg_patch.start()
        lock_patch.start()
        self.addCleanup(reg_patch.stop)
        self.addCleanup(lock_patch.stop)

    def test_add_row_writes_qrs_full_header(self):
        ws = FakeWorksheet([self.HEADER_A_S])
        res = add_product_row(
            "Woolworths 12 Extra Large Free Range Eggs 700g",
            "woolworths", 5.00, size="700g", worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertTrue(res["item_code"])
        # ONE full-row update, range covers A:S.
        self.assertEqual(len(ws.updates), 1)
        _values, range_name = ws.updates[0]
        self.assertEqual(range_name, "A2:S2")
        updated = ws.get_all_values()
        self.assertEqual(updated[1][16], "eggs")     # Col Q classified
        self.assertEqual(updated[1][17], res["item_code"])
        self.assertEqual(updated[1][18], "")         # Col S empty
        self.assertTrue(item_codes.is_valid_code(res["item_code"]))

    def test_add_row_subcategory_override_flag(self):
        ws = FakeWorksheet([self.HEADER_A_S])
        res = add_product_row(
            "Some Odd Named Thing 500g", "coles", 4.00, size="500g",
            subcategory="Eggs ", worksheet=ws)
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][16], "eggs")  # normalised override

    def test_add_row_unclassifiable_gets_needs_review(self):
        ws = FakeWorksheet([self.HEADER_A_S])
        res = add_product_row(
            "AJI CRISPY FRY BREADING MIX ORIGINAL 62g", "coles", 3.00,
            size="62g", worksheet=ws)
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][16], "needs review")

    def test_add_row_without_qrs_header_unchanged_width(self):
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
            "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
            "Keywords",
        ]
        ws = FakeWorksheet([header])
        res = add_product_row(
            "Fresh Milk 2L", "woolworths", 3.10, size="2L",
            worksheet=ws)
        self.assertTrue(res["wrote"])
        # No Q/R/S headers: row still written, 16 cols wide (A:P).
        _values, range_name = ws.updates[0]
        self.assertEqual(range_name, "A2:P2")
        self.assertEqual(res["item_code"], "")

    def test_add_row_merge_leaves_qrs_untouched(self):
        ws = FakeWorksheet([
            self.HEADER_A_S,
            ["Obela Classic Hommus 200g", "Dairy", "200g", "4.50",
             "", "", "Obela", "", "obela hommus", "", "", "", "", "",
             "", "hommus", "dip", "QRS", "P"],
        ])
        res = add_product_row(
            "Woolworths Hommus Classic Obela 200g", "woolworths", 4.20,
            brand="Obela", size="200g", worksheet=ws)
        self.assertTrue(res["merged"])
        # No new row; existing Q/R/S cells byte-identical.
        updated = ws.get_all_values()
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[1][16], "dip")
        self.assertEqual(updated[1][17], "QRS")
        self.assertEqual(updated[1][18], "P")

    def test_add_row_registry_confirmed(self):
        ws = FakeWorksheet([self.HEADER_A_S])
        res = add_product_row(
            "Woolworths White Bread 650g", "woolworths", 2.40,
            size="650g", worksheet=ws)
        self.assertTrue(res["wrote"])
        registry = item_codes.load_registry()
        self.assertIn(res["item_code"], registry)
        self.assertEqual(
            registry[res["item_code"]]["row"], res["row_index"])


class TestSpecialsCellCodec(unittest.TestCase):
    """_specials_cell M/N encoding (D25 + §7.2, plan §S14)."""

    def test_specials_cell_for_promo_encodes_terms(self):
        from core.sheets_sync import _specials_cell
        self.assertEqual(
            _specials_cell(True, "2 for $6.00"), "multi-buy 2/$6.00")

    def test_specials_cell_any_promo_encodes_terms(self):
        # USER REVISION 2026-09-05 (D-MB3 retired): "Any N | $X"
        # deals are rate-eligible — the cell encodes their terms.
        from core.sheets_sync import _specials_cell
        self.assertEqual(
            _specials_cell(True, "Any 2 | $9"), "multi-buy 2/$9.00")

    def test_specials_cell_discount_unchanged(self):
        from core.sheets_sync import _specials_cell
        self.assertEqual(
            _specials_cell(True, "Was $5.00, save $1.00"), "discount")
        self.assertEqual(
            _specials_cell(True, "Save $2.00"), "discount")

    def test_specials_cell_no_unchanged(self):
        from core.sheets_sync import _specials_cell
        self.assertEqual(_specials_cell(False, ""), "no")

    def test_decode_roundtrip_via_multibuy(self):
        # The encoded cell decodes back to (qty, total) terms.
        from core.sheets_sync import _specials_cell
        from core.multibuy import decode_multibuy_cell
        cell = _specials_cell(True, "2 for $6.00")
        self.assertEqual(decode_multibuy_cell(cell), (2, 6.0))

    def test_update_single_price_encodes_multibuy_cell(self):
        # Site 2: update_single_price specials write carries terms.
        header = [
            "Product_Name", "Category", "Size", "Woolworths_Price",
            "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
            "Search_Keyword_Woolworths", "Search_Keyword_Coles",
            "Search_Keyword_Aldi", "Aldi_Refresh",
            "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
            "Keywords",
        ]
        ws = FakeWorksheet([
            header,
            ["Full Cream Milk", "Dairy", "2L", "4.00", "", "", "", "",
             "", "", "", "", "no", "", "", ""],
        ])
        res = update_single_price(
            "Full Cream Milk", "woolworths", 3.00,
            is_special=True, special_desc="2 for $6.00", worksheet=ws)
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][12], "multi-buy 2/$6.00")  # Col M


class TestMultibuyPriceCell(unittest.TestCase):
    """USER RULE 2026-09-05: multi-buy items write the per-unit deal
    rate into the price cell on ALL THREE write paths (the saving must
    be evident in sheet comparisons). Bundle terms stay in M/N."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def test_sync_prices_writes_deal_rate_for_style(self):
        ws = FakeWorksheet([
            self.HEADER,
            ["Cola 2L", "Drinks", "2L", "4.00", "", "", "", "",
             "", "", "", "", "no", "", "", ""],
        ])
        results = [MatchResult(True, 2, "Cola 2L", "woolworths",
                               "Cola 2L", "exact_keyword")]
        items = [ProductItem("woolworths", "WW Cola 2L", 4.00,
                             is_special=True, special_desc="2 for $7.00")]
        sync_prices(results, items, worksheet=ws)
        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], 3.5)   # 7.00 / 2 deal rate
        self.assertEqual(updated[1][12], "multi-buy 2/$7.00")

    def test_update_single_price_writes_deal_rate_any_style(self):
        # D-MB3 retired: "Any 2 | $9" is a rate-eligible deal.
        ws = FakeWorksheet([
            self.HEADER,
            ["Sunbites", "Snacks", "200g", "6.00", "", "", "", "",
             "", "", "", "", "no", "", "", ""],
        ])
        res = update_single_price(
            "Sunbites", "woolworths", 6.00,
            is_special=True, special_desc="Any 2 | $9.00", worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertEqual(res["new_price"], 4.5)  # 9.00 / 2
        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], 4.5)
        self.assertEqual(updated[1][12], "multi-buy 2/$9.00")

    def test_update_single_price_plain_price_untouched(self):
        ws = FakeWorksheet([
            self.HEADER,
            ["Milk", "Dairy", "2L", "3.20", "", "", "", "",
             "", "", "", "", "no", "", "", ""],
        ])
        res = update_single_price(
            "Milk", "woolworths", 3.50,
            is_special=True, special_desc="Save $0.50", worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertEqual(res["new_price"], 3.5)  # no multibuy terms
        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], 3.5)
        self.assertEqual(updated[1][12], "discount")

    def test_update_single_price_no_specials_leaves_raw(self):
        # is_special=None: caller asked to leave specials untouched —
        # no transform (a deal desc without a specials write would
        # desync price vs cell).
        ws = FakeWorksheet([
            self.HEADER,
            ["Milk", "Dairy", "2L", "3.20", "", "", "", "",
             "", "", "", "", "no", "", "", ""],
        ])
        res = update_single_price(
            "Milk", "woolworths", 4.00, worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertEqual(res["new_price"], 4.0)
        updated = ws.get_all_values()
        self.assertEqual(updated[1][3], 4.0)

    def test_add_product_row_writes_deal_rate(self):
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row(
            "Zero Sugar Coke 10x375ml", "coles", 11.50,
            size="10x375ml", is_special=True,
            special_desc="2 for $23.00", worksheet=ws)
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][4], 11.5)  # 23.00 / 2 deal rate
        self.assertEqual(updated[1][13], "multi-buy 2/$23.00")


class TestAddProductRowHalalHooks(unittest.TestCase):
    """S20: halal keep-apart + Col P/S ingestion hook (§12.6)."""

    HEADER = TestAddProductRowOneLineRule.HEADER + [
        "Sub_Category", "Item_Code", "Preferred",
    ]

    def _ws(self, col_p=""):
        rows = [
            self.HEADER,
            ["Obela Classic Hommus 200g", "Dairy", "200g", "4.50",
             "", "", "Obela", "", "obela hommus", "", "", "", "", "",
             "", col_p, "", "", ""],
        ]
        return FakeWorksheet(rows)

    def test_marked_vs_unmarked_twins_do_not_merge(self):
        """Different halal status -> NEVER merge (keep-apart)."""
        from core.sheets_sync import add_product_row
        ws = self._ws(col_p="fresh|halal")
        res = add_product_row(
            "Obela Hommus Classic 200g", "woolworths", 4.20,
            brand="Obela", size="200g", worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertNotEqual(res.get("existing_name"),
                            "Obela Classic Hommus 200g")
        self.assertEqual(len(ws.get_all_values()), 3)

    def test_same_status_products_merge_marker_survives(self):
        """Same halal status -> merge; the marker survives via
        _append_alias."""
        from core.sheets_sync import add_product_row
        ws = self._ws(col_p="fresh|halal")
        res = add_product_row(
            "Obela Hommus Classic 200g", "woolworths", 4.20,
            brand="Obela", size="200g", alias="dip",
            halal_confirmed=True, worksheet=ws)
        self.assertTrue(res["merged"])
        updated = ws.get_all_values()
        self.assertIn("halal", updated[1][15].split("|"))
        self.assertIn("dip", updated[1][15].split("|"))

    def test_halal_confirmed_add_writes_marker_and_P(self):
        """Tier-2 auto-add: Col P gains 'halal'; auto-scope -> P."""
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row(
            "Halal Beef Mince BrandX 500g", "woolworths", 9.50,
            size="500g", halal_confirmed=True, worksheet=ws)
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertIn("halal", updated[1][15].split("|"))
        self.assertEqual(updated[1][18], "P")

    def test_halal_add_clears_non_halal_P_in_subcategory(self):
        """P-alignment goes through set_preferred (single writer)."""
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([self.HEADER])
        with patch("core.preferences.set_preferred",
                   return_value={"wrote": True}) as sp:
            res = add_product_row(
                "Halal Beef Mince BrandX 500g", "woolworths", 9.50,
                size="500g", halal_confirmed=True, worksheet=ws)
        self.assertTrue(res["wrote"])
        sp.assert_called_once()

    def test_auto_scope_unknown_row_flagged_pending_check(self):
        """Non-marked auto-scope add -> halal_pending_check True."""
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row(
            "Woolworths Beef Mince 1kg", "woolworths", 11.0,
            size="1kg", worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertTrue(res["halal_pending_check"])

    def test_dry_run_writes_nothing_including_halal_fields(self):
        """dry_run: no write; result still carries the flag key."""
        from core.sheets_sync import add_product_row
        ws = FakeWorksheet([self.HEADER])
        res = add_product_row(
            "Halal Beef Mince BrandX 500g", "woolworths", 9.50,
            size="500g", halal_confirmed=True, dry_run=True,
            worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertEqual(len(ws.get_all_values()), 1)
        self.assertIn("halal_pending_check", res)


if __name__ == "__main__":
    unittest.main()


class TestAddPathVolumeIntegrity(unittest.TestCase):
    """FIX-9 (D16): add-path anomalies at volume — the 500-item
    battery saw 3 phantom "already tracked (row N)" refusals where N
    was the refused item's OWN future row, and more sheet rows than
    successful adds. Offline: written-count MUST equal created-rows,
    zero refusals, zero merges — and a corrupted write becomes LOUD."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def test_387_unique_adds_written_count_equals_rows(self):
        ws = FakeWorksheet([list(self.HEADER)])
        wrote = merged = refused = 0
        refusal_errors: list = []
        for i in range(1, 388):
            name = f"ZWidget Type {i:03d} 500g"
            res = add_product_row(
                generic_name=name,
                store="woolworths",
                price=round(1.0 + (i % 90) * 0.1, 2),
                brand="",
                size="500g",
                worksheet=ws,
            )
            if res.get("wrote") and not res.get("merged"):
                wrote += 1
            elif res.get("merged"):
                merged += 1
            else:
                refused += 1
                refusal_errors.append((name, res.get("error", "")))
        data = [r for r in ws.get_all_values()[1:]
                if str(r[0]).strip()]
        self.assertEqual(refused, 0, refusal_errors[:3])
        self.assertEqual(merged, 0)
        self.assertEqual(wrote, 387)
        self.assertEqual(len(data), 387)      # rows == written-count
        names = [str(r[0]).strip() for r in data]
        self.assertEqual(len(set(names)), 387)   # all unique, no dups

    def test_corrupted_write_raises_loudly(self):
        """A write that lands wrong (the live anomaly class) raises
        RuntimeError — never a silent wrote=True."""

        class _LyingWorksheet(FakeWorksheet):
            def update(self, *, values, range_name):
                # Simulate the phantom: the write lands with the
                # WRONG name (concurrent writer / shifted index).
                import copy
                corrupted = copy.deepcopy(list(values))
                corrupted[0][0] = "SOMEONE ELSE'S ROW"
                super().update(values=corrupted,
                               range_name=range_name)

        ws = _LyingWorksheet([list(self.HEADER)])
        with self.assertRaises(RuntimeError) as ctx:
            add_product_row(
                generic_name="Probe Widget 250g",
                store="woolworths", price=2.0, brand="",
                size="250g", worksheet=ws,
            )
        self.assertIn("add verify failed", str(ctx.exception))


class TestVariantBehaviorConsistent(unittest.TestCase):
    """FIX-10 (D17): ONE documented behavior for name variants at the
    add path — exact (case-preserved) matches are refused; word-order
    and lowercase variants go to the one-line rule and MERGE (price +
    alias update)."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def _ws(self, name):
        return FakeWorksheet([
            list(self.HEADER),
            [name, "Cat", "2L", "$3.00", "", "", "", "", "", "", "",
             "", "", "", "", "old alias"],
        ])

    def test_exact_name_refused(self):
        ws = self._ws("Full Cream Milk 2L")
        res = add_product_row(
            generic_name="Full Cream Milk 2L",   # byte-identical
            store="coles", price=2.90, brand="", size="2L",
            alias="milk", worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertFalse(res["merged"])
        self.assertIn("already tracked", res["error"])
        # No price/alias update on a refusal.
        grid = ws.get_all_values()
        self.assertEqual(grid[1][4], "")          # Coles price untouched
        self.assertEqual(grid[1][15], "old alias")

    def test_word_order_variant_merges(self):
        ws = self._ws("Full Cream Milk 2L")
        res = add_product_row(
            generic_name="2L Milk Full Cream",
            store="coles", price=2.90, brand="", size="2L",
            alias="milk", worksheet=ws)
        self.assertTrue(res["merged"])
        grid = ws.get_all_values()
        self.assertEqual(grid[1][4], 2.90)        # price updated
        self.assertIn("old alias", grid[1][15])   # alias appended
        self.assertIn("milk", grid[1][15])

    def test_lowercase_variant_merges(self):
        ws = self._ws("Full Cream Milk 2L")
        res = add_product_row(
            generic_name="full cream milk 2l",
            store="coles", price=2.70, brand="", size="2L",
            alias="milk", worksheet=ws)
        self.assertTrue(res["merged"])
        grid = ws.get_all_values()
        self.assertEqual(grid[1][4], 2.70)
        self.assertIn("milk", grid[1][15])


class TestSizeTokenReorderMergeR2_3(unittest.TestCase):
    """R2-3 (D22): a word-reorder that moves the size token ("14 pack"
    -> "pack … 14") must MERGE into the canonical row — the size
    extraction is order-independent, the merge key can no longer split.
    Real-sheet names from the verification round's t8 run 3 Phase B."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def _ws(self):
        return FakeWorksheet([
            list(self.HEADER),
            ["Evamay Pads With Wings Super 14 pack", "Health", "14 pack",
             "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ])

    def test_reorder_moving_pack_word_merges(self):
        # The exact D22 variant: "pack" moved to the front leaves a
        # bare trailing "14" — must still MERGE, not append.
        ws = self._ws()
        res = add_product_row(
            generic_name="pack Evamay Pads With Wings Super 14",
            store="coles", price=10.0, brand="", size="14 pack",
            alias="evamay pads", worksheet=ws)
        self.assertTrue(res["merged"])
        self.assertTrue(res["wrote"])
        grid = ws.get_all_values()
        self.assertEqual(len(grid), 2)             # NO appended row
        self.assertEqual(grid[1][0],
                         "Evamay Pads With Wings Super 14 pack")
        self.assertEqual(grid[1][4], 10.0)         # price merged in

    def test_reorder_battery_all_merge(self):
        # The reorder/lowercase variant battery shape from the t8 run
        # — every true variant of the canonical name merges offline.
        variants = [
            "pack Evamay Pads With Wings Super 14",      # D22 case
            "Evamay Pads With Wings Super pack 14",      # unit before num
            "evamay pads with wings super 14 pack",      # lowercase
            "Super 14 pack Evamay Pads With Wings",      # suffix moved
            "14 pack Evamay Pads With Wings Super",      # prefix moved
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                ws = self._ws()
                res = add_product_row(
                    generic_name=variant,
                    store="coles", price=9.5, brand="", size="14 pack",
                    alias="", worksheet=ws)
                self.assertTrue(res["merged"], res)
                self.assertEqual(len(ws.get_all_values()), 2)

    def test_exact_duplicate_still_refused(self):
        ws = self._ws()
        res = add_product_row(
            generic_name="Evamay Pads With Wings Super 14 pack",
            store="coles", price=9.0, brand="", size="14 pack",
            worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertFalse(res["merged"])
        self.assertIn("already tracked", res["error"])

    def test_different_unit_amount_still_appends(self):
        # The 20% same-unit rule survives the order-independent pass:
        # 200g vs 400g is a DIFFERENT amount of the same unit.
        ws = FakeWorksheet([
            list(self.HEADER),
            ["Evamay Pads With Wings Super 200g", "Health", "200g",
             "", "", "", "", "", "", "", "", "", "", "", "", ""],
        ])
        res = add_product_row(
            generic_name="Evamay Pads With Wings Super 400g",
            store="coles", price=12.0, brand="", size="400g",
            worksheet=ws)
        self.assertTrue(res["wrote"])
        self.assertFalse(res.get("merged", False))
        self.assertEqual(len(ws.get_all_values()), 3)


class _GridCappedWorksheet(FakeWorksheet):
    """Fake with a gspread-style grid capacity (R2-11/R17): `.rows`
    is the grid limit; add_rows() grows it."""

    def __init__(self, rows_data, grid_rows):
        super().__init__(rows_data)
        self.rows = grid_rows
        self.add_rows_calls = []

    def add_rows(self, n):
        self.add_rows_calls.append(n)
        self.rows += n


class TestGridCeilingGuardR2_11(unittest.TestCase):
    """R2-11 (R17): appending at the grid limit expands the grid (with
    headroom) instead of dying on APIError [400] 'exceeds grid limits'
    (t8 run 1 crashed on add #381 of 387)."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def _ws(self, n_data_rows, grid_rows, fail_expand=False):
        rows = [list(self.HEADER)] + [
            [f"Bulk Filler Item {i:04d}", "Cat", "1kg", "", "", "", "",
             "", "", "", "", "", "", "", "", ""]
            for i in range(n_data_rows)
        ]
        ws = _GridCappedWorksheet(rows, grid_rows)

        if fail_expand:
            def _boom(n):
                raise RuntimeError("simulated API failure")
            ws.add_rows = _boom
        return ws

    def test_append_at_limit_expands_grid_with_headroom(self):
        # 380 data rows on a 381-row grid: the append targets row 382
        # — the grid expands FIRST (>= GRID_EXPAND_HEADROOM rows), the
        # add succeeds, nothing raises.
        from core.sheets_sync import GRID_EXPAND_HEADROOM
        ws = self._ws(n_data_rows=380, grid_rows=381)
        res = add_product_row(
            generic_name="New Item At The Ceiling 500g",
            store="coles", price=3.5, brand="", size="500g",
            worksheet=ws)
        self.assertTrue(res["wrote"], res)
        self.assertEqual(ws.add_rows_calls, [GRID_EXPAND_HEADROOM])
        self.assertEqual(len(ws.get_all_values()), 382)

    def test_headroom_present_never_expands(self):
        # Grid has room — the guard is a no-op.
        ws = self._ws(n_data_rows=10, grid_rows=381)
        res = add_product_row(
            generic_name="New Item With Room 500g",
            store="coles", price=3.5, brand="", size="500g",
            worksheet=ws)
        self.assertTrue(res["wrote"], res)
        self.assertEqual(ws.add_rows_calls, [])

    def test_failed_expansion_returns_clear_error(self):
        # Expansion fails -> a CLEAR actionable error dict, never a
        # raw APIError escaping mid-bulk.
        ws = self._ws(n_data_rows=380, grid_rows=381, fail_expand=True)
        res = add_product_row(
            generic_name="New Item Blocked Ceiling 500g",
            store="coles", price=3.5, brand="", size="500g",
            worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertFalse(res.get("merged", False))
        self.assertIn("grid is full", res["error"])
        self.assertIn("add rows", res["error"])
        # Nothing was appended.
        self.assertEqual(len(ws.get_all_values()), 381)


# ============================================================================
# R3-1 (R2-11 residue): the grid guard must key on gspread 6.2.1's REAL
# attribute — `.row_count` — not `.rows`. The fakes below mirror the
# real Worksheet surface (row_count present, .rows absent, update()
# past the grid raises the same raw APIError [400] the live battery
# saw), so the at-limit test FAILS against the old `.rows`-keyed
# helper — this is the test that would have caught R2-11.
# ============================================================================


class _FakeAPIResponse:
    """Minimal requests.Response stand-in for APIError(response)."""

    def __init__(self, code, message):
        self.status_code = code
        self.text = message
        self._payload = {"error": {
            "code": code, "message": message, "status": "INVALID_ARGUMENT"}}

    def json(self):
        return self._payload


class _GspreadRealWorksheet(FakeWorksheet):
    """Fake exposing ONLY gspread 6.2.1's real attribute surface:
    `.row_count` grid capacity (deliberately NO `.rows` — real
    worksheets have none), `add_rows()` growth, and an APIError [400]
    'exceeds grid limits' on any update() past the grid — the exact
    live failure mode (t8/t8r2_c_run.log, verification round 2)."""

    def __init__(self, rows_data, row_count):
        super().__init__(rows_data)
        self.row_count = row_count
        self.add_rows_calls = []

    def add_rows(self, n):
        self.add_rows_calls.append(n)
        self.row_count += n

    def update(self, *, values, range_name):
        _sr, _sc, end_row, _ec = _parse_range(range_name)
        if end_row > self.row_count:
            raise APIError(_FakeAPIResponse(
                400, f"Range ({range_name}) exceeds grid limits. "
                     f"Max rows: {self.row_count}"))
        super().update(values=values, range_name=range_name)


class TestGridCeilingGuardR3_1(unittest.TestCase):
    """R3-1: against a fake with gspread 6.2.1's REAL attribute surface
    (row_count present, .rows ABSENT) the guard still engages — the
    R2-11 helper keyed on `.rows`, read None here, and let the raw
    APIError [400] escape (two live crashes, verification round 2)."""

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def _ws(self, n_data_rows, row_count, fail_expand=False):
        rows = [list(self.HEADER)] + [
            [f"Bulk Filler Item {i:04d}", "Cat", "1kg", "", "", "", "",
             "", "", "", "", "", "", "", "", ""]
            for i in range(n_data_rows)
        ]
        ws = _GspreadRealWorksheet(rows, row_count)
        if fail_expand:
            def _boom(n):
                raise RuntimeError("simulated API failure")
            ws.add_rows = _boom
        return ws

    def test_fake_mirrors_real_gspread_surface(self):
        # The fake must NOT expose `.rows` — gspread 6.2.1 has none. If
        # it did, the guard could pass for the wrong reason. And the
        # helper must read the REAL attribute, `row_count`.
        from core.sheets_sync import _worksheet_grid_rows
        ws = self._ws(n_data_rows=3, row_count=380)
        self.assertFalse(hasattr(ws, "rows"))
        self.assertEqual(_worksheet_grid_rows(ws), 380)

    def test_append_at_limit_expands_grid_no_raw_400(self):
        # The R3-1 acceptance core: 380 data rows on a 381-row grid —
        # the append targets row 382, the grid expands FIRST (with
        # headroom), the write lands, and NO raw APIError escapes.
        # Under the R2-11 helper this fake read as unknown-grid and the
        # raw APIError [400] 'exceeds grid limits' propagated.
        from core.sheets_sync import GRID_EXPAND_HEADROOM
        ws = self._ws(n_data_rows=380, row_count=381)
        res = add_product_row(
            generic_name="New Item At The Ceiling 500g",
            store="coles", price=3.5, brand="", size="500g",
            worksheet=ws)
        self.assertTrue(res["wrote"], res)
        self.assertEqual(ws.add_rows_calls, [GRID_EXPAND_HEADROOM])
        self.assertEqual(ws.row_count, 381 + GRID_EXPAND_HEADROOM)
        self.assertEqual(len(ws.get_all_values()), 382)

    def test_headroom_present_never_expands(self):
        # Grid has room — the guard is a no-op even on the real-surface
        # fake.
        ws = self._ws(n_data_rows=10, row_count=381)
        res = add_product_row(
            generic_name="New Item With Room 500g",
            store="coles", price=3.5, brand="", size="500g",
            worksheet=ws)
        self.assertTrue(res["wrote"], res)
        self.assertEqual(ws.add_rows_calls, [])

    def test_failed_expansion_returns_clear_error(self):
        # Expansion fails -> a CLEAR actionable error dict, never the
        # raw APIError.
        ws = self._ws(n_data_rows=380, row_count=381, fail_expand=True)
        res = add_product_row(
            generic_name="New Item Blocked Ceiling 500g",
            store="coles", price=3.5, brand="", size="500g",
            worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertFalse(res.get("merged", False))
        self.assertIn("grid is full", res["error"])
        self.assertIn("add rows", res["error"])
        self.assertEqual(len(ws.get_all_values()), 381)


# ============================================================================
# R2-15 (D15): legacy BARE "multi-buy" markers — a payload WITH deal
# terms upgrades the cell to the encoded form (rate applies on the
# price write); with NO terms the marker stays UNTOUCHED and the row
# is listed once in the Wednesday summary (multibuy_awaiting_terms).
# ============================================================================


class TestBareMultibuyMarkerR2_15(unittest.TestCase):

    HEADER = [
        "Product_Name", "Category", "Size", "Woolworths_Price",
        "Coles_Price", "Aldi_Price", "Brand_Type", "Last_Updated",
        "Search_Keyword_Woolworths", "Search_Keyword_Coles",
        "Search_Keyword_Aldi", "Aldi_Refresh",
        "Woolworths_Specials", "Coles_Specials", "Rewards_Points",
        "Keywords",
    ]

    def _ws(self, specials_cell):
        return FakeWorksheet([
            list(self.HEADER),
            ["Energy Drink 6 Pack", "Drinks", "6x250ml", "", "", "",
             "", "", "WW Energy Drink 6 Pack", "", "", "",
             specials_cell, "", "", ""],
            # A second row matched this run — its presence makes the
            # store's list "provided", so the D25 not-found pass RUNS
            # over the (absent) Energy row.
            ["Milk 2L", "Dairy", "2L", "", "", "", "", "",
             "WW Milk 2L", "", "", "", "", "", "", ""],
        ])

    def _milk(self):
        return ([MatchResult(
            True, 3, "Milk 2L", "woolworths", "WW Milk 2L",
            "exact_keyword")],
            [ProductItem("woolworths", "WW Milk 2L", 3.00)])

    def test_payload_with_terms_upgrades_bare_marker(self):
        ws = self._ws("multi-buy")     # legacy bare marker
        results = [MatchResult(
            True, 2, "Energy Drink 6 Pack", "woolworths",
            "WW Energy Drink 6 Pack", "exact_keyword")]
        items = [ProductItem(
            "woolworths", "WW Energy Drink 6 Pack", 6.00,
            is_special=True, special_desc="2 for $6.00")]
        report = sync_prices(results, items, worksheet=ws)
        grid = ws.get_all_values()
        # Cell upgraded to the full terms form...
        self.assertEqual(grid[1][12], "multi-buy 2/$6.00")
        # ...and the deal RATE landed on the price write.
        self.assertEqual(float(grid[1][3]), 3.00)
        # Upgraded rows are not "awaiting terms".
        self.assertEqual(report.multibuy_awaiting_terms, [])

    def test_no_terms_leaves_marker_and_reports_it(self):
        ws = self._ws("multi-buy")     # absent from this week's list
        results, items = self._milk()
        report = sync_prices(results, items, worksheet=ws)
        grid = ws.get_all_values()
        # Marker untouched (was: cleared to "no" by the D25 pass).
        self.assertEqual(grid[1][12], "multi-buy")
        # ...and the gap is VISIBLE once per sync.
        self.assertEqual(report.multibuy_awaiting_terms,
                         ["Energy Drink 6 Pack (woolworths)"])

    def test_other_stale_vocabulary_still_clears_to_no(self):
        # Only the BARE multi-buy marker survives; stale "discount"
        # and stale ENCODED terms still clear for absent rows (D25).
        for stale in ("discount", "multi-buy 2/$7.00"):
            with self.subTest(stale=stale):
                ws = self._ws(stale)
                results, items = self._milk()
                report = sync_prices(results, items, worksheet=ws)
                grid = ws.get_all_values()
                self.assertEqual(grid[1][12], "no")
                self.assertEqual(report.multibuy_awaiting_terms, [])
