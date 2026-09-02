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
        self.assertEqual(updated[1][13], "multi-buy")   # N: Any 2 | $9
        self.assertEqual(updated[2][13], "no")          # N: not special
        self.assertEqual(updated[3][13], "50% off")     # unmatched: kept

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
        ws = self._ws()
        res = update_single_price(
            "Oat Milk", "coles", 3.50, worksheet=ws,
            is_special=True, special_desc="2 for $4")
        self.assertTrue(res["wrote"])
        updated = ws.get_all_values()
        self.assertEqual(updated[1][13], "multi-buy")


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

    def test_normalized_match_refused(self):
        from core.sheets_sync import add_product_row
        ws = self._ws_with_milk()
        res = add_product_row(
            "  woolworths   FULL cream milk 3l ", "woolworths", 4.30,
            brand="Woolworths", size="3L", worksheet=ws)
        self.assertFalse(res["wrote"])
        self.assertIn("already tracked", res["error"])

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
        (multi-buy stays multi-buy; the pass never overwrites them)."""
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
        self.assertEqual(updated[1][12], "multi-buy")


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


if __name__ == "__main__":
    unittest.main()
