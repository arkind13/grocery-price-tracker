#!/usr/bin/env python3
"""Pure unit tests for Phase 5: CLI dispatch + missing-items tracker.

No network, no live sheet. Uses FakeWorksheet mock pattern.
"""
from __future__ import annotations
import argparse
import io
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))
_ROOT = _PROJECT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ============================================================================
# FakeWorksheet (reuse pattern from test_sheets_sync.py)
# ============================================================================

class FakeWorksheet:
    """Mock gspread Worksheet for unit testing."""
    def __init__(self, rows):
        self._values = [list(r) for r in rows]
        self.updates = []
        self.added_cols = 0

    def get_all_values(self):
        return [list(r) for r in self._values]

    def update(self, *, values, range_name):
        self.updates.append((values, range_name))
        sr, sc, er, ec = _parse_range(range_name)
        for row_offset, row_vals in enumerate(values):
            r = sr + row_offset - 1
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


def _parse_range(range_name: str) -> tuple:
    m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
    if not m:
        raise ValueError(f"Cannot parse range: {range_name}")
    sc = _col_letter_to_idx(m.group(1))
    sr = int(m.group(2))
    ec = _col_letter_to_idx(m.group(3))
    er = int(m.group(4))
    return sr, sc, er, ec


def _col_letter_to_idx(letter: str) -> int:
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch.upper()) - ord('A') + 1)
    return idx - 1


def _make_header(base_only: bool = False) -> list:
    header = [
        "Product_Name", "Category", "Size", "Woolworths_Price", "Coles_Price",
        "Aldi_Price", "Brand_Type", "Last_Updated", "Search_Keyword_Woolworths",
        "Search_Keyword_Coles", "Search_Keyword_Aldi", "Aldi_Refresh",
    ]
    if not base_only:
        header.extend(["Woolworths_Specials", "Coles_Specials", "Rewards_Points"])
    return header


# ============================================================================
# Test classes
# ============================================================================

class TestCLI(unittest.TestCase):
    """Tests for CLI dispatch, missing-items tracker, and output formatting."""

    # ========================================================================
    # CLI dispatch tests
    # ========================================================================

    def test_parser_all_subcommands(self):
        """build_parser registers all 9 subcommands."""
        from grocery_price_cli import build_parser
        parser = build_parser()
        # Help output lists all 9
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            with self.assertRaises(SystemExit):
                parser.parse_args(["--help"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        for cmd in ["specials", "rewards", "compare", "search", "recipe",
                     "update", "sync", "specials-scan", "unmapped"]:
            self.assertIn(cmd, output)

    def test_unknown_command_exit_2(self):
        """Unknown subcommand exits with code 2."""
        from grocery_price_cli import build_parser
        parser = build_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["nonexistent"])
        self.assertEqual(ctx.exception.code, 2)

    def test_missing_required_arg_exit_2(self):
        """Missing --items on compare exits with code 2."""
        from grocery_price_cli import build_parser
        parser = build_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["compare"])
        self.assertEqual(ctx.exception.code, 2)

    # ========================================================================
    # _cmd_unmapped tests
    # ========================================================================

    @patch("core.name_matcher.get_pending_mappings")
    def test_unmapped_empty_queue(self, mock_get):
        """Empty queue prints 'No pending unmapped items.'"""
        from grocery_price_cli import _cmd_unmapped
        mock_get.return_value = []
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_unmapped(None)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("No pending", output)

    @patch("core.name_matcher.get_pending_mappings")
    def test_unmapped_populated_queue(self, mock_get):
        """Populated queue renders table with N rows."""
        from grocery_price_cli import _cmd_unmapped
        mock_get.return_value = [
            {
                "store": "woolworths",
                "raw_name": "Test Item 1",
                "classification": {"brand": "TestBrand", "size": "1L", "category": "Dairy"},
                "count": 3,
            },
            {
                "store": "coles",
                "raw_name": "Test Item 2",
                "classification": {"brand": "", "size": "", "category": ""},
                "count": 1,
            },
        ]
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_unmapped(None)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("Test Item 1", output)
        self.assertIn("Test Item 2", output)
        self.assertIn("Total:", output)

    # ========================================================================
    # _cmd_update tests
    # ========================================================================

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._load_env")
    def test_update_not_found_exit_1(self, mock_env, mock_update):
        """Product not found returns exit 1 with stderr message."""
        from grocery_price_cli import _cmd_update
        mock_update.return_value = {"found": False, "error": "product not found"}
        args = argparse.Namespace(
            product="Nonexistent", store="woolworths", price=1.00, dry_run=False
        )
        old_stderr = sys.stderr
        try:
            sys.stderr = io.StringIO()
            code = _cmd_update(args)
        finally:
            sys.stderr = old_stderr
        self.assertEqual(code, 1)

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._load_env")
    def test_update_dry_run_success(self, mock_env, mock_update):
        """Dry-run prints [DRY RUN] marker and exits 0."""
        from grocery_price_cli import _cmd_update
        mock_update.return_value = {
            "found": True, "row_index": 5, "old_price": 4.50,
            "new_price": 4.20, "range_written": "D5",
        }
        args = argparse.Namespace(
            product="Oatly Milk", store="woolworths", price=4.20, dry_run=True
        )
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_update(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("[DRY RUN]", output)

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._load_env")
    def test_update_invalid_price_exit_1(self, mock_env, mock_update):
        """Price <= 0 exits 1."""
        from grocery_price_cli import _cmd_update
        args = argparse.Namespace(
            product="Milk", store="woolworths", price=0, dry_run=False
        )
        old_stderr = sys.stderr
        try:
            sys.stderr = io.StringIO()
            code = _cmd_update(args)
        finally:
            sys.stderr = old_stderr
        self.assertEqual(code, 1)

    # ========================================================================
    # Missing-items tracker tests
    # ========================================================================

    def test_update_missing_items_symmetric_disjoint(self):
        """Two lists with disjoint matched names produce correct counts."""
        from core.missing_items_tracker import update_missing_items

        class FakeMatchResult:
            def __init__(self, matched, generic_name, raw_name, store):
                self.matched = matched
                self.generic_name = generic_name
                self.raw_name = raw_name
                self.store = store

        ww_results = [
            FakeMatchResult(True, "Milk", "Woolworths Milk 2L", "woolworths"),
            FakeMatchResult(True, "Bread", "Woolworths Bread 650g", "woolworths"),
        ]
        coles_results = [
            FakeMatchResult(True, "Eggs", "Coles Eggs 12pk", "coles"),
            FakeMatchResult(True, "Cheese", "Coles Cheese 500g", "coles"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            from core import missing_items_tracker as mit
            with patch.object(mit, "WOOLWORTHS_MISSING_PATH",
                              Path(tmpdir) / "woolworths_missing_items.json"), \
                 patch.object(mit, "COLES_MISSING_PATH",
                              Path(tmpdir) / "coles_missing_items.json"):
                result = mit.update_missing_items(ww_results, coles_results)
                self.assertEqual(result["woolworths_missing"], 2)  # Eggs, Cheese
                self.assertEqual(result["coles_missing"], 2)        # Milk, Bread

    def test_update_missing_items_idempotent_upsert(self):
        """Same item on second run increments count, bumps last_seen."""
        from core.missing_items_tracker import update_missing_items

        class FakeMatchResult:
            def __init__(self, matched, generic_name, raw_name, store):
                self.matched = matched
                self.generic_name = generic_name
                self.raw_name = raw_name
                self.store = store

        ww_results = [
            FakeMatchResult(True, "Milk", "Woolworths Milk 2L", "woolworths"),
        ]
        coles_results = []  # No Coles items -> Milk is "missing from Coles"

        with tempfile.TemporaryDirectory() as tmpdir:
            from core import missing_items_tracker as mit
            ww_path = Path(tmpdir) / "ww_missing.json"
            coles_path = Path(tmpdir) / "coles_missing.json"
            with patch.object(mit, "WOOLWORTHS_MISSING_PATH", ww_path), \
                 patch.object(mit, "COLES_MISSING_PATH", coles_path), \
                 patch.dict(mit.MISSING_PATH_BY_STORE,
                            {"woolworths": ww_path, "coles": coles_path}):

                # First run
                result1 = mit.update_missing_items(ww_results, coles_results)
                self.assertEqual(result1["coles_missing"], 1)

                # Read the queue
                coles_q = mit.get_missing_items("coles")
                self.assertEqual(len(coles_q), 1)
                first_seen = coles_q[0]["first_seen"]
                self.assertEqual(coles_q[0]["count"], 1)

                # Second run -- same item
                result2 = mit.update_missing_items(ww_results, coles_results)
                self.assertEqual(result2["coles_missing"], 1)

                coles_q2 = mit.get_missing_items("coles")
                self.assertEqual(coles_q2[0]["first_seen"], first_seen)
                self.assertNotEqual(coles_q2[0]["last_seen"], first_seen)
                self.assertEqual(coles_q2[0]["count"], 2)

    def test_update_missing_items_one_empty_list(self):
        """One empty list -> all of other store's items are missing for it."""
        from core.missing_items_tracker import update_missing_items

        class FakeMatchResult:
            def __init__(self, matched, generic_name, raw_name, store):
                self.matched = matched
                self.generic_name = generic_name
                self.raw_name = raw_name
                self.store = store

        ww_results = [
            FakeMatchResult(True, "Milk", "Woolworths Milk 2L", "woolworths"),
            FakeMatchResult(True, "Bread", "Woolworths Bread 650g", "woolworths"),
        ]
        coles_results = []  # Empty

        with tempfile.TemporaryDirectory() as tmpdir:
            from core import missing_items_tracker as mit
            with patch.object(mit, "WOOLWORTHS_MISSING_PATH",
                              Path(tmpdir) / "ww_missing.json"), \
                 patch.object(mit, "COLES_MISSING_PATH",
                              Path(tmpdir) / "coles_missing.json"):
                result = mit.update_missing_items(ww_results, coles_results)
                self.assertEqual(result["woolworths_missing"], 0)
                self.assertEqual(result["coles_missing"], 2)

    def test_update_missing_items_unmatched_excluded(self):
        """Unmatched results are excluded from the diff."""
        from core.missing_items_tracker import update_missing_items

        class FakeMatchResult:
            def __init__(self, matched, generic_name, raw_name, store):
                self.matched = matched
                self.generic_name = generic_name
                self.raw_name = raw_name
                self.store = store

        ww_results = [
            FakeMatchResult(True, "Milk", "Woolworths Milk 2L", "woolworths"),
            FakeMatchResult(False, "", "Unknown WW Item", "woolworths"),
        ]
        coles_results = [
            FakeMatchResult(True, "Bread", "Coles Bread 650g", "coles"),
            FakeMatchResult(False, "", "Unknown Coles Item", "coles"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            from core import missing_items_tracker as mit
            with patch.object(mit, "WOOLWORTHS_MISSING_PATH",
                              Path(tmpdir) / "ww_missing.json"), \
                 patch.object(mit, "COLES_MISSING_PATH",
                              Path(tmpdir) / "coles_missing.json"):
                result = mit.update_missing_items(ww_results, coles_results)
                # Only "Milk" and "Bread" counted -- unmatched excluded
                self.assertEqual(result["woolworths_missing"], 1)  # Bread
                self.assertEqual(result["coles_missing"], 1)        # Milk

    def test_clear_missing_removes_entry(self):
        """clear_missing removes entry by product name (idempotent)."""
        from core.missing_items_tracker import (
            _read_queue, _write_queue, clear_missing, get_missing_items,
        )

        now = datetime.now(timezone.utc).isoformat()
        entry = {
            "product_name": "Test Product",
            "normalized_key": "test product",
            "source_store": "coles",
            "first_seen": now,
            "last_seen": now,
            "count": 1,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_missing.json"
            _write_queue(path, [entry])

            from core import missing_items_tracker as mit
            with patch.object(mit, "WOOLWORTHS_MISSING_PATH", path):
                clear_missing("woolworths", "Test Product")
                remaining = get_missing_items("woolworths")
                self.assertEqual(len(remaining), 0)

                # Idempotent -- clearing again does not raise
                clear_missing("woolworths", "Test Product")
                self.assertEqual(len(get_missing_items("woolworths")), 0)

    def test_format_missing_summary_emojis(self):
        """format_missing_summary includes emoji labels and counts."""
        from core.missing_items_tracker import format_missing_summary

        # Mock get_pending_mappings and get_missing_items
        # format_missing_summary imports get_pending_mappings internally
        with patch("core.name_matcher.get_pending_mappings",
                   return_value=[{}, {}]), \
             patch("core.missing_items_tracker.get_missing_items",
                   side_effect=lambda store: {
                       "woolworths": [{"a": 1}],
                       "coles": [{"a": 1}, {"b": 2}],
                   }.get(store, [])):
            output = format_missing_summary()
            self.assertIn("\U0001f4dd", output)
            self.assertIn("\u274c", output)
            self.assertIn("Unmapped items: 2", output)
            self.assertIn("Woolworths missing items", output)
            self.assertIn("Coles missing items", output)

    def test_read_queue_corrupt_json_returns_empty(self):
        """Corrupt JSON file is treated as empty queue."""
        from core.missing_items_tracker import _read_queue
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "corrupt.json"
            path.write_text("not valid json {{{")
            result = _read_queue(path)
            self.assertEqual(result, [])

    def test_read_queue_missing_file_returns_empty(self):
        """Missing file returns empty list."""
        from core.missing_items_tracker import _read_queue
        path = Path(tempfile.gettempdir()) / "nonexistent_missing.json"
        result = _read_queue(path)
        self.assertEqual(result, [])

    def test_update_missing_items_both_empty(self):
        """Both lists empty -> empty queues, 0/0 counts."""
        from core.missing_items_tracker import update_missing_items

        with tempfile.TemporaryDirectory() as tmpdir:
            from core import missing_items_tracker as mit
            with patch.object(mit, "WOOLWORTHS_MISSING_PATH",
                              Path(tmpdir) / "ww_missing.json"), \
                 patch.object(mit, "COLES_MISSING_PATH",
                              Path(tmpdir) / "coles_missing.json"):
                result = mit.update_missing_items([], [])
                self.assertEqual(result["woolworths_missing"], 0)
                self.assertEqual(result["coles_missing"], 0)
                self.assertEqual(mit.get_missing_items("woolworths"), [])
                self.assertEqual(mit.get_missing_items("coles"), [])

    # ========================================================================
    # Exit-code contract tests
    # ========================================================================

    def test_main_exits_0_on_help(self):
        """main() returns 0 when --help is passed (argparse default)."""
        from grocery_price_cli import main
        with patch.object(sys, "argv", ["grocery_price_cli.py", "--help"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)

    def test_main_exits_2_on_unknown_command(self):
        """main() exits 2 on unknown command."""
        from grocery_price_cli import main
        with patch.object(sys, "argv", ["grocery_price_cli.py", "bogus"]):
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 2)

    # ========================================================================
    # Search handler tests
    # ========================================================================

    @patch("extractors.coles_extractor.fetch_coles_search")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_both_stores_empty(self, mock_ww, mock_coles):
        """Both stores return empty -> 'No results found'."""
        from grocery_price_cli import _cmd_search
        mock_ww.return_value = []
        mock_coles.return_value = []
        args = argparse.Namespace(product="nonexistent")
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_search(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("No results found", output)

    # ========================================================================
    # Rewards handler tests
    # ========================================================================

    @patch("core.specials_reporter.get_bonus_rewards")
    @patch("grocery_price_cli._load_env")
    def test_rewards_empty_column_o(self, mock_env, mock_rewards):
        """Empty rewards -> 'column O not populated' notice."""
        from grocery_price_cli import _cmd_rewards
        mock_rewards.return_value = []
        args = argparse.Namespace(store="all")
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_rewards(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("column O not populated", output)

    # ========================================================================
    # Compare handler tests
    # ========================================================================

    @patch("core.price_comparator.format_report")
    @patch("core.price_comparator.compare_basket")
    @patch("grocery_price_cli._load_env")
    def test_compare_sheet_mode_cheapest_store(self, mock_env, mock_compare, mock_format):
        """compare in sheet mode produces cheapest-store line."""
        from grocery_price_cli import _cmd_compare
        from core.price_comparator import ComparisonReport, BasketItem

        item = BasketItem(
            name="Milk", prices={"woolworths": 3.00, "coles": 2.80},
            sources={"woolworths": "sheet", "coles": "sheet"},
        )
        report = ComparisonReport(
            items=[item],
            raw_totals={"woolworths": 3.00, "coles": 2.80},
            store_coverage={"woolworths": 1, "coles": 1},
            final_totals={"woolworths": 3.00, "coles": 2.80},
            cheapest_store="coles",
            most_expensive_store="woolworths",
            max_savings=0.20,
            not_available={"woolworths": [], "coles": [], "aldi": ["Milk"]},
        )
        mock_compare.return_value = report
        mock_format.return_value = "**Cheapest store:** Coles\n**Max savings:** $0.20"

        args = argparse.Namespace(
            items="milk", mode="sheet", team_discount=True, extra_discount=0.0,
        )
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_compare(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("Cheapest store", output)

    # ========================================================================
    # Specials handler tests
    # ========================================================================

    @patch("grocery_price_cli._load_env")
    def test_specials_sheet_mode_no_results(self, mock_env):
        """specials with no active specials returns graceful message."""
        from grocery_price_cli import _cmd_specials
        from unittest.mock import patch as upatch

        # _cmd_specials also calls fetch_woolworths_list() as live fallback
        with upatch("core.specials_reporter.get_active_specials", return_value=[]), \
             upatch("core.specials_reporter.format_specials_report", return_value="No active specials."), \
             upatch("extractors.woolworths_extractor.fetch_woolworths_list", return_value=[]):
            args = argparse.Namespace(store="all")
            old_stdout = sys.stdout
            try:
                sys.stdout = io.StringIO()
                code = _cmd_specials(args)
                output = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
            self.assertEqual(code, 0)
            self.assertIn("No active specials", output)

    # ========================================================================
    # Phase 9.7.d — search (noauth), map, compare --mode auto tests
    # ========================================================================

    @patch("extractors.coles_extractor.fetch_coles_search")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_with_results_cheapest(self, mock_ww, mock_coles):
        """search returns cheapest store when both stores have results."""
        from grocery_price_cli import _cmd_search
        from extractors.models import ProductItem

        mock_ww.return_value = [
            ProductItem("woolworths", "WW Milk 2L", 3.50),
        ]
        mock_coles.return_value = [
            ProductItem("coles", "Coles Milk 2L", 3.20),
        ]
        args = argparse.Namespace(product="milk")
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_search(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("Cheapest", output)
        self.assertIn("Woolworths", output)
        self.assertIn("Coles", output)

    @patch("extractors.coles_extractor.fetch_coles_search")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_with_specials(self, mock_ww, mock_coles):
        """search shows special badge when item is on special."""
        from grocery_price_cli import _cmd_search
        from extractors.models import ProductItem

        mock_ww.return_value = [
            ProductItem("woolworths", "WW Milk 2L", 3.50,
                        is_special=True, special_desc="Half Price"),
        ]
        mock_coles.return_value = []
        args = argparse.Namespace(product="milk")
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_search(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("Half Price", output)

    @patch("extractors.coles_extractor.fetch_coles_search")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_woolworths_exception_fallback(self, mock_ww, mock_coles):
        """search handles Woolworths exception gracefully, still shows Coles."""
        from grocery_price_cli import _cmd_search
        from extractors.models import ProductItem

        mock_ww.side_effect = RuntimeError("curl_cffi error")
        mock_coles.return_value = [
            ProductItem("coles", "Coles Milk 2L", 3.20),
        ]
        args = argparse.Namespace(product="milk")
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        try:
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            code = _cmd_search(args)
            output = sys.stdout.getvalue()
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
        self.assertEqual(code, 0)
        self.assertIn("Coles", output)
        self.assertIn("unavailable", stderr_output)

    def test_map_subcommand_registered(self):
        """map subcommand is registered in the parser."""
        from grocery_price_cli import build_parser
        parser = build_parser()
        # parse map status (no-op read)
        args = parser.parse_args(["map", "status"])
        self.assertEqual(args.list_name, "status")

    def test_map_choices_reject_bad_list(self):
        """map subcommand rejects invalid list names."""
        from grocery_price_cli import build_parser
        parser = build_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["map", "bogus"])
        self.assertEqual(ctx.exception.code, 2)

    def test_parser_includes_all_phase9_subcommands(self):
        """Parser registers all Phase 9 subcommands: search, map, wednesday."""
        from grocery_price_cli import build_parser
        parser = build_parser()
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            with self.assertRaises(SystemExit):
                parser.parse_args(["--help"])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        for cmd in ["search", "map", "wednesday", "compare", "update"]:
            self.assertIn(cmd, output)

    @patch("core.price_comparator.format_report")
    @patch("core.price_comparator.compare_basket")
    @patch("grocery_price_cli._load_env")
    def test_compare_auto_mode_flag(self, mock_env, mock_compare, mock_format):
        """compare --mode auto passes through to compare_basket."""
        from grocery_price_cli import _cmd_compare
        from core.price_comparator import ComparisonReport, BasketItem

        item = BasketItem(
            name="Milk", prices={"woolworths": 3.00},
            sources={"woolworths": "live"},
        )
        report = ComparisonReport(
            items=[item],
            raw_totals={"woolworths": 3.00},
            store_coverage={"woolworths": 1},
            final_totals={"woolworths": 3.00},
            cheapest_store="woolworths",
            most_expensive_store="woolworths",
            max_savings=0.0,
            not_available={"woolworths": [], "coles": ["Milk"], "aldi": ["Milk"]},
        )
        mock_compare.return_value = report
        mock_format.return_value = "**Cheapest store:** Woolworths"

        args = argparse.Namespace(
            items="milk", mode="auto", team_discount=False, extra_discount=0.0,
        )
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_compare(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("Woolworths", output)

    # ========================================================================
    # Always-on Woolworths display discounts — CLI surface tests
    # ========================================================================

    @patch("extractors.coles_extractor.fetch_coles_search")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_cheapest_uses_discounted_ww(self, mock_ww, mock_coles):
        """Discounting can flip the cheapest store: WW home-brand $4.00
        -> $3.61 beats raw Coles $3.80; Coles rows stay raw."""
        from grocery_price_cli import _cmd_search
        from extractors.models import ProductItem

        mock_ww.return_value = [
            ProductItem("woolworths", "Macro Milk 2L", 4.00,
                        brand="Macro"),
        ]
        mock_coles.return_value = [
            ProductItem("coles", "Coles Milk 2L", 3.80),
        ]
        args = argparse.Namespace(product="milk")
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_search(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        # WW cell: discounted price prominent + raw visible.
        self.assertIn("$3.61 (Home 9.75% off, was $4.00)", output)
        # Cheapest computed on the DISCOUNTED WW value.
        self.assertIn("**Cheapest:** Woolworths at $3.61", output)

    @patch("core.specials_reporter.get_bonus_rewards")
    @patch("grocery_price_cli._load_env")
    def test_rewards_discount_only_woolworths_rows(
            self, mock_env, mock_rewards):
        """Price cell discounted only when the reward's store is WW."""
        from grocery_price_cli import _cmd_rewards
        mock_rewards.return_value = [
            {"name": "Macro Oats", "rewards": "500 pts",
             "price": 4.00, "store": "woolworths",
             "brand": "Macro Wholefoods Market"},
            {"name": "Bega Cheese", "rewards": "300 pts",
             "price": 5.00, "store": "coles", "brand": "Bega"},
        ]
        args = argparse.Namespace(store="all")
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_rewards(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("Home 9.75% off, was $4.00", output)  # WW discounted
        self.assertIn("| $5.00 |", output)                   # Coles raw
        self.assertNotIn("was $5.00", output)


class BatchFakeWorksheet(FakeWorksheet):
    """FakeWorksheet plus gspread's batch_update for backfill tests."""
    def __init__(self, rows):
        super().__init__(rows)
        self.batch_calls = []

    def batch_update(self, cells):
        self.batch_calls.append(list(cells))
        return len(cells)


class TestBackfillHomeBrands(unittest.TestCase):
    """backfill-home-brands: dry-run planning + one batched live write."""

    @staticmethod
    def _rows():
        header = _make_header()
        return [
            header,
            # Empty G + leading name label -> planned.
            ["Macro Rolled Oats 1kg", "", "", "$6.00", "", "",
             "", "", "", "", "", ""],
            # Non-matching non-empty G -> skipped by default.
            ["Bega Cheese Block", "", "", "", "$8.00", "",
             "Bega", "", "", "", "", ""],
            # Matching-value G ("Woolworths BBQ") -> normalized to Home.
            ["BBQ Sausages 400g", "", "", "$7.50", "", "",
             "Woolworths BBQ", "", "", "", "", ""],
            # Already 'Home' -> idempotent skip.
            ["Odd Bunch Apples", "", "", "", "", "",
             "Home", "", "", "", "", ""],
            # Name matches but brand cell says otherwise:
            # only planned WITH --overwrite.
            ["Essentials Paper Towel 2pk", "Household", "2pk", "$2.00",
             "", "", "Generic Brand", "", "", "", "", ""],
        ]

    @patch("core.sheets_client.connect_worksheet")
    @patch("grocery_price_cli._load_env")
    def test_dry_run_plans_without_writing(self, mock_env, mock_conn):
        from grocery_price_cli import _cmd_backfill_home_brands
        ws = BatchFakeWorksheet(self._rows())
        mock_conn.return_value = ws
        args = argparse.Namespace(dry_run=True, overwrite=False)
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_backfill_home_brands(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        self.assertIn("[DRY RUN]", output)
        # Rows 2 (name match) and 4 (matching value) planned.
        self.assertIn("| 2 | Macro Rolled Oats 1kg |", output)
        self.assertIn("| 4 | BBQ Sausages 400g | Woolworths BBQ | Home |",
                      output)
        # Skips: already-Home row 5; non-matching Bega row 3; not in plan.
        self.assertNotIn("| 3 |", output)
        self.assertNotIn("| 5 |", output)
        self.assertNotIn("| 6 |", output)
        self.assertEqual(ws.batch_calls, [])

    @patch("core.sheets_client.connect_worksheet")
    @patch("grocery_price_cli._load_env")
    def test_live_write_one_batch(self, mock_env, mock_conn):
        from grocery_price_cli import _cmd_backfill_home_brands
        ws = BatchFakeWorksheet(self._rows())
        mock_conn.return_value = ws
        args = argparse.Namespace(dry_run=False, overwrite=True)
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_backfill_home_brands(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        # --overwrite adds row 6 via name-match override.
        self.assertIn("Wrote 3 Col G cell(s)", output)
        self.assertEqual(len(ws.batch_calls), 1)  # ONE batched update
        ranges = [c["range"] for c in ws.batch_calls[0]]
        self.assertEqual(ranges, ["G2", "G4", "G6"])
        values = [c["values"][0][0] for c in ws.batch_calls[0]]
        self.assertEqual(values, ["Home", "Home", "Home"])


class TestWednesdaySpecialsDisplay(unittest.TestCase):
    """Light check of the Wednesday Step-8 table discounting."""

    def test_step8_lines_contain_discounted_prices(self):
        """Docx items carry no brand -> name fallback classifies home
        brands (9.75%) while regular items get the flat 5%."""
        from grocery_price_cli import _build_ww_specials_lines
        items = [
            {"name": "Macro Rolled Oats 900g", "price": 4.00,
             "detail": "Half Price"},
            {"name": "Arnott's Tim Tams 200g", "price": 5.00,
             "detail": "save $1.00"},
        ]
        lines = _build_ww_specials_lines(items)
        text = "\n".join(lines)
        self.assertIn("$3.61 (Home 9.75% off, was $4.00)", text)
        self.assertIn("$4.75 (5% off, was $5.00)", text)
        self.assertIn("**Total:** 2 specials", text)


if __name__ == "__main__":
    unittest.main()
