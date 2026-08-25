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
import time as time_module
import unittest
from pathlib import Path

# Bootstrap sys.path so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent  # tests/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.schema_upgrade import (
    EXPECTED_BASE_HEADERS,
    NEW_COLUMNS,
    audit_schema,
    upgrade_schema,
)
from core.sheets_sync import (
    sync_prices, update_single_price, _update_with_backoff, _find_col,
    add_product_row, mark_not_available, set_store_keyword,
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
        # Coles_Specials is at index 14 (N)
        self.assertEqual(updated[1][14], "Half Price")

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
        # Stale specials cleared
        self.assertEqual(updated[1][14], "")

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
        self.assertEqual(updated[1][3], 3.50)                # Col D
        self.assertEqual(updated[1][6], "TestBrand")         # Col G
        self.assertTrue(updated[1][7])                        # Col H
        self.assertEqual(updated[1][8], "Woolworths Test Milk 2L")  # Col I
        self.assertEqual(updated[1][15], "test milk")         # Col P

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
            dry_run=True, worksheet=ws,
        )
        self.assertFalse(result["wrote"])
        self.assertEqual(result["row_index"], 3)  # would be row 3
        self.assertEqual(len(ws.updates), 0)

    # ------------------------------------------------------------------ #
    # Test 23: add_product_row validation failures
    # ------------------------------------------------------------------ #
    def test_add_product_row_validation_failures(self):
        ws = FakeWorksheet([["H1"]])

        # Unknown store
        r1 = add_product_row("Milk", "iga", 4.00, worksheet=ws)
        self.assertFalse(r1["wrote"])
        self.assertIn("unknown store", r1["error"])

        # Empty name
        r2 = add_product_row("", "woolworths", 4.00, worksheet=ws)
        self.assertFalse(r2["wrote"])
        self.assertIn("generic_name", r2["error"])

        # Price <= 0
        r3 = add_product_row("Milk", "woolworths", 0, worksheet=ws)
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


if __name__ == "__main__":
    unittest.main()
