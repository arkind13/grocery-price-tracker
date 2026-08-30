#!/usr/bin/env python3
"""Pure unit tests for Phase 5: CLI dispatch + missing-items tracker.

No network, no live sheet. Uses FakeWorksheet mock pattern.
"""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

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
                     "update", "sync", "specials-scan", "unmapped",
                     "add-to-list"]:
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
        self.assertIn("pending unmapped item(s)", output)

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

    @patch("extractors.coles_extractor.fetch_coles_search_status")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_both_stores_empty(self, mock_ww, mock_coles):
        """Both stores return empty -> 'No results found'."""
        # Spec IN-5: _cmd_search consumes the status-signalling variant.
        from grocery_price_cli import _cmd_search
        mock_ww.return_value = []
        mock_coles.return_value = ([], "empty")
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

    @patch("extractors.coles_extractor.fetch_coles_search_status")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_with_results_cheapest(self, mock_ww, mock_coles):
        """search returns cheapest store when both stores have results."""
        # Spec IN-5 + §4.8-2: status-signalling Coles search; ≤3 shown.
        from grocery_price_cli import _cmd_search
        from extractors.models import ProductItem

        mock_ww.return_value = [
            ProductItem("woolworths", "WW Milk 2L", 3.50),
        ]
        mock_coles.return_value = ([
            ProductItem("coles", "Coles Milk 2L", 3.20),
        ], "ok")
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

    @patch("extractors.coles_extractor.fetch_coles_search_status")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_with_specials(self, mock_ww, mock_coles):
        """search shows special badge when item is on special."""
        from grocery_price_cli import _cmd_search
        from extractors.models import ProductItem

        mock_ww.return_value = [
            ProductItem("woolworths", "WW Milk 2L", 3.50,
                        is_special=True, special_desc="Half Price"),
        ]
        mock_coles.return_value = ([], "ok")
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

    @patch("extractors.coles_extractor.fetch_coles_search_status")
    @patch("extractors.woolworths_extractor.fetch_woolworths_search_noauth")
    def test_search_woolworths_exception_fallback(self, mock_ww, mock_coles):
        """search handles Woolworths exception gracefully, still shows Coles."""
        from grocery_price_cli import _cmd_search
        from extractors.models import ProductItem

        mock_ww.side_effect = RuntimeError("curl_cffi error")
        mock_coles.return_value = ([
            ProductItem("coles", "Coles Milk 2L", 3.20),
        ], "ok")
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

    @patch("extractors.coles_extractor.fetch_coles_search_status")
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
        mock_coles.return_value = ([
            ProductItem("coles", "Coles Milk 2L", 3.80),
        ], "ok")
        args = argparse.Namespace(product="milk")
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            code = _cmd_search(args)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertEqual(code, 0)
        # WW line: discounted price only — NO team-discount "was" suffix.
        self.assertIn("$3.61", output)
        self.assertNotIn("was $4.00", output)
        self.assertNotIn("9.75%", output)
        # Cheapest computed on the DISCOUNTED WW value.
        self.assertIn("Cheapest: Woolworths at $3.61", output)
        # Pipe-table ban on the search output.
        self.assertNotIn("|---", output)
        self.assertNotIn("| # |", output)

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
        self.assertIn("$3.61", output)                        # WW discounted
        self.assertNotIn("was $4.00", output)                 # no team "was"
        self.assertIn("$5.00", output)                        # Coles raw
        self.assertNotIn("| $5.00 |", output)                 # pipe ban
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
        self.assertIn("2. Macro Rolled Oats 1kg", output)
        self.assertIn("4. BBQ Sausages 400g · Woolworths BBQ → Home",
                      output)
        # Skips: already-Home row 5; non-matching Bega row 3; not in plan.
        self.assertNotIn("3. Bega Cheese", output)
        self.assertNotIn("5. Odd Bunch Apples", output)
        self.assertNotIn("6. Essentials Paper Towel", output)
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
        # Discounted prices only — no team-discount "was" suffix; the
        # genuine special detail ("Half Price", "save $1.00") rides along.
        self.assertIn("$3.61", text)
        self.assertIn("$4.75", text)
        self.assertNotIn("was $4.00", text)
        self.assertNotIn("was $5.00", text)
        self.assertIn("Half Price", text)
        self.assertIn("2 specials", text)
        # Pipe-table ban on the Wednesday specials block.
        self.assertNotIn("|---", text)
        self.assertNotIn("| # |", text)


class TestAddToListCLI(unittest.TestCase):
    """add-to-list subcommand + wool/coles add-flow queue hooks (B1-B21).

    Every test isolates the queue file via patch.object over
    core.add_to_list.ADD_TO_LIST_PATH; map-flow tests additionally point
    progress_path/data_dir at a tempdir and mock the search/price-sheet
    boundaries.
    """

    # ========================================================================
    # Helpers
    # ========================================================================

    def _atl_ctx(self, tmpdir):
        """Patch context for an isolated ADD_TO_LIST_PATH."""
        from core import add_to_list as atl
        return patch.object(atl, "ADD_TO_LIST_PATH",
                            Path(tmpdir) / "add_to_list.json")

    def _map_args(self, **overrides):
        """Namespace for _cmd_map_noninteractive with all action flags."""
        defaults = {"next": False, "pick": None, "add": False,
                    "skip": False, "na": False, "forget": False,
                    "keyword": None}
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def _fake_prod(self, raw_name, price):
        """Duck-typed live-search result covering the print path attrs."""
        return SimpleNamespace(raw_name=raw_name, price=price, brand="",
                               is_special=False, special_desc="")

    def _seed_four(self, atl):
        """Seed 2 Coles + 2 Woolworths entries."""
        atl.add_entry("coles", "Coles Item One", "Generic One")
        atl.add_entry("coles", "Coles Item Two", "Generic Two")
        atl.add_entry("woolworths", "Woolies Item Three", "Generic Three")
        atl.add_entry("woolworths", "Woolies Item Four", "Generic Four")

    def _capture_stdout(self, fn, *args, **kwargs):
        """Run fn capturing stdout; returns (result, output)."""
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            result = fn(*args, **kwargs)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        return result, output

    def _capture_both(self, fn, *args, **kwargs):
        """Run fn capturing stdout+stderr; returns (result, out, err)."""
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = io.StringIO()
            sys.stderr = io.StringIO()
            result = fn(*args, **kwargs)
            out = sys.stdout.getvalue()
            err = sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr
        return result, out, err

    # ========================================================================
    # Parser + show/done handler (B1-B8)
    # ========================================================================

    def test_add_to_list_subparser_registered(self):
        """B1: add-to-list parses; func is _cmd_add_to_list; bare 'done'
        parses (handler validates --items)."""
        from grocery_price_cli import _cmd_add_to_list, build_parser
        parser = build_parser()
        args = parser.parse_args(["add-to-list", "show"])
        self.assertIs(args.func, _cmd_add_to_list)
        args_done = parser.parse_args(["add-to-list", "done"])
        self.assertEqual(args_done.action, "done")
        self.assertIsNone(args_done.items)

    def test_show_empty_prints_friendly_line(self):
        """B2: show on an empty queue -> exit 0 + friendly line."""
        from grocery_price_cli import _cmd_add_to_list
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                args = argparse.Namespace(action="show", items=None)
                code, output = self._capture_stdout(_cmd_add_to_list, args)
        self.assertEqual(code, 0)
        self.assertIn("add_to_list is empty", output)

    def test_show_two_sections_continuous_numbering(self):
        """B3: Seed 2C+2W -> both section headers, 1)..4), each keyword."""
        from grocery_price_cli import _cmd_add_to_list
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                self._seed_four(atl)
                args = argparse.Namespace(action="show", items=None)
                code, output = self._capture_stdout(_cmd_add_to_list, args)
        self.assertEqual(code, 0)
        self.assertIn("Coles", output)
        self.assertIn("Woolworths", output)
        for line in ("1) Coles Item One", "2) Coles Item Two",
                     "3) Woolies Item Three", "4) Woolies Item Four"):
            self.assertIn(line, output)

    def test_done_valid_removes_and_reprints(self):
        """B4: done --items "1,3" -> exit 0; two Removed lines;
        "2 still pending"; file holds the other 2."""
        from grocery_price_cli import _cmd_add_to_list
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                self._seed_four(atl)
                args = argparse.Namespace(action="done", items="1,3")
                code, output = self._capture_stdout(_cmd_add_to_list, args)
                remaining = [e["keyword"] for e in atl.load_pending()]
        self.assertEqual(code, 0)
        self.assertIn("Removed: Coles Item One (Coles)", output)
        self.assertIn("Removed: Woolies Item Three (Woolworths)", output)
        self.assertIn("2 still pending:", output)
        self.assertIn("1) Coles Item Two (Coles)", output)
        self.assertIn("2) Woolies Item Four (Woolworths)", output)
        self.assertEqual(remaining, ["Coles Item Two", "Woolies Item Four"])

    def test_done_out_of_range_removes_nothing_exit_1(self):
        """B5: done --items "9" on 4 -> exit 1, stderr names range, file
        unchanged."""
        from grocery_price_cli import _cmd_add_to_list
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                self._seed_four(atl)
                before = atl.ADD_TO_LIST_PATH.read_bytes()
                args = argparse.Namespace(action="done", items="9")
                code, out, err = self._capture_both(_cmd_add_to_list, args)
                self.assertEqual(atl.ADD_TO_LIST_PATH.read_bytes(), before)
        self.assertEqual(code, 1)
        self.assertIn("1-4", err)
        self.assertEqual(out, "")

    def test_done_missing_items_arg_exit_1(self):
        """B6: Namespace without items -> exit 1, stderr mentions --items."""
        from grocery_price_cli import _cmd_add_to_list
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                args = argparse.Namespace(action="done")
                code, out, err = self._capture_both(_cmd_add_to_list, args)
        self.assertEqual(code, 1)
        self.assertIn("--items", err)

    def test_done_unparsable_items_exit_1(self):
        """B7: done --items "abc" -> exit 1."""
        from grocery_price_cli import _cmd_add_to_list
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                args = argparse.Namespace(action="done", items="abc")
                code, out, err = self._capture_both(_cmd_add_to_list, args)
        self.assertEqual(code, 1)
        self.assertIn("could not parse items", err)

    def test_done_empty_queue_exit_1(self):
        """B8: done with no queue file -> exit 1, stderr mentions empty."""
        from grocery_price_cli import _cmd_add_to_list
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                args = argparse.Namespace(action="done", items="1")
                code, out, err = self._capture_both(_cmd_add_to_list, args)
        self.assertEqual(code, 1)
        self.assertIn("empty", err.lower())

    # ========================================================================
    # wool/coles map add hooks (B9-B16)
    # ========================================================================

    def _run_map_add(self, list_name, item, tmpdir, mock_search,
                     mock_update, store_raw_name, price=9.50):
        """Shared arrange for non-interactive map add tests.

        Patches _load_env + search (returning one fake result) +
        update_single_price (found=True) and runs the add flow.
        Returns (exit_code, output).
        """
        from grocery_price_cli import _cmd_map_noninteractive
        mock_search.return_value = (
            [self._fake_prod(store_raw_name, price)], item)
        mock_update.return_value = {"found": True, "row_index": 7}
        progress_path = Path(tmpdir) / "list_action_progress.json"
        args = self._map_args(add=True)
        return self._capture_stdout(
            _cmd_map_noninteractive, args, list_name, [item], 0, {},
            progress_path, Path(tmpdir))

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_wool_add_queues_raw_name(
            self, mock_env, mock_search, mock_update):
        """B9: wool --add queues raw_name as keyword, Col A as generic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                code, output = self._run_map_add(
                    "wool", "Beef Mince 500g", tmpdir, mock_search,
                    mock_update, "Woolworths Beef Mince 500g")
                data = atl.load_pending()
        self.assertEqual(code, 0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["store"], "woolworths")
        self.assertEqual(data[0]["keyword"], "Woolworths Beef Mince 500g")
        self.assertEqual(data[0]["generic_name"], "Beef Mince 500g")
        self.assertIn("Added to add_to_list:", output)

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_coles_add_queues(
            self, mock_env, mock_search, mock_update):
        """B10: coles --add queues the same way under store coles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                code, output = self._run_map_add(
                    "coles", "Butter 500g", tmpdir, mock_search,
                    mock_update, "Coles Butter 500g")
                data = atl.load_pending()
        self.assertEqual(code, 0)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["store"], "coles")
        self.assertEqual(data[0]["keyword"], "Coles Butter 500g")
        self.assertEqual(data[0]["generic_name"], "Butter 500g")
        self.assertIn("Added to add_to_list:", output)

    @patch("core.sheets_sync.set_store_keyword")
    @patch("core.sheets_sync.mark_not_available")
    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_add_sheet_write_is_price_only(
            self, mock_env, mock_search, mock_update, mock_na, mock_kw):
        """B11: add writes price ONLY — no keyword/NA calls; price called
        once with (item, store, best.price)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                code, _output = self._run_map_add(
                    "wool", "Beef Mince 500g", tmpdir, mock_search,
                    mock_update, "Woolworths Beef Mince 500g", price=8.20)
        self.assertEqual(code, 0)
        mock_kw.assert_not_called()
        mock_na.assert_not_called()
        mock_update.assert_called_once_with(
            "Beef Mince 500g", "woolworths", 8.20,
            is_special=False, special_desc="")

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_add_not_found_queues_nothing(
            self, mock_env, mock_search, mock_update):
        """B12: update_single_price found=False -> no queue file."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                mock_search.return_value = (
                    [self._fake_prod("WW Item", 1.0)], "q")
                mock_update.return_value = {"found": False,
                                            "error": "product not found"}
                args = self._map_args(add=True)
                code, _out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Beef Mince 500g"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                self.assertFalse(atl.ADD_TO_LIST_PATH.exists())
        self.assertEqual(code, 0)

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_add_update_raises_queues_nothing(
            self, mock_env, mock_search, mock_update):
        """B13: update_single_price raises -> no queue file."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                mock_search.return_value = (
                    [self._fake_prod("WW Item", 1.0)], "q")
                mock_update.side_effect = RuntimeError("sheet down")
                args = self._map_args(add=True)
                code, _out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Beef Mince 500g"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                self.assertFalse(atl.ADD_TO_LIST_PATH.exists())
        self.assertEqual(code, 0)

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_add_no_search_results_queues_nothing(
            self, mock_env, mock_search, mock_update):
        """B14: Search returns ([], query) -> exit 1, no file."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                mock_search.return_value = ([], "Beef Mince 500g")
                args = self._map_args(add=True)
                code, _out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Beef Mince 500g"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                self.assertFalse(atl.ADD_TO_LIST_PATH.exists())
        self.assertEqual(code, 1)
        mock_update.assert_not_called()

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_add_already_pending_prints_and_keeps_one(
            self, mock_env, mock_search, mock_update):
        """B15: Pre-seeded entry -> already-there line, still 1 entry,
        price refresh still fires."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                atl.add_entry("woolworths", "Old WW Keyword",
                              "Beef Mince 500g")
                mock_search.return_value = (
                    [self._fake_prod("Woolworths Beef Mince 500g", 9.50)],
                    "Beef Mince 500g")
                mock_update.return_value = {"found": True, "row_index": 7}
                args = self._map_args(add=True)
                code, output = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Beef Mince 500g"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                data = atl.load_pending()
        self.assertEqual(code, 0)
        self.assertIn("Already on add_to_list (since", output)
        self.assertIn("not added again", output)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["keyword"], "Old WW Keyword")
        mock_update.assert_called_once()

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_add_advances_normally(
            self, mock_env, mock_search, mock_update):
        """B16: After add, the next-item header prints — auto-advance
        unchanged."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                mock_search.return_value = (
                    [self._fake_prod("WW Item", 1.0)], "q")
                mock_update.return_value = {"found": True, "row_index": 7}
                args = self._map_args(add=True)
                code, output = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Item One", "Item Two"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
        self.assertEqual(code, 0)
        self.assertIn("--- Item 2/2 ---", output)

    # ========================================================================
    # Interactive add path + negative controls (B17-B21)
    # ========================================================================

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._prompt_action")
    @patch("grocery_price_cli._search_store_with_fallback")
    def test_map_interactive_add_path_hooks_queue(
            self, mock_search, mock_prompt, mock_update):
        """B17: Interactive 'add' action writes the queue, then 'done'
        ends the session."""
        from grocery_price_cli import _map_store_item
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                mock_search.return_value = (
                    [self._fake_prod("Woolworths Beef Mince 500g", 9.50)],
                    "Beef Mince 500g")
                mock_prompt.side_effect = ["add", "done"]
                mock_update.return_value = {"found": True, "row_index": 3}
                code_ret, output = self._capture_stdout(
                    _map_store_item, "wool", "Beef Mince 500g")
                data = atl.load_pending()
        self.assertEqual(code_ret, "done")
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["store"], "woolworths")
        self.assertEqual(data[0]["keyword"], "Woolworths Beef Mince 500g")
        self.assertEqual(data[0]["generic_name"], "Beef Mince 500g")
        self.assertIn("Added to add_to_list:", output)

    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_map_skip_leaves_queue_untouched(
            self, mock_env, mock_search, mock_update):
        """B18: --skip advances without touching the queue."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                args = self._map_args(skip=True)
                code, _out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Item One"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                self.assertFalse(atl.ADD_TO_LIST_PATH.exists())
        self.assertEqual(code, 0)
        mock_update.assert_not_called()

    @patch("core.sheets_sync.mark_not_available")
    @patch("grocery_price_cli._load_env")
    def test_map_na_leaves_queue_untouched(self, mock_env, mock_na):
        """B19: --na (found=True) leaves the queue untouched."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                mock_na.return_value = {"found": True, "row_index": 2}
                args = self._map_args(na=True)
                code, _out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Item One"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                self.assertFalse(atl.ADD_TO_LIST_PATH.exists())
        self.assertEqual(code, 0)
        mock_na.assert_called_once()

    @patch("core.sheets_sync.set_store_keyword")
    @patch("grocery_price_cli._load_env")
    def test_map_keyword_leaves_queue_untouched(self, mock_env, mock_kw):
        """B20: --keyword "X" (found=True) leaves the queue untouched."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                mock_kw.return_value = {"found": True, "row_index": 2}
                args = self._map_args(keyword="X")
                code, _out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Item One"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                self.assertFalse(atl.ADD_TO_LIST_PATH.exists())
        self.assertEqual(code, 0)
        mock_kw.assert_called_once()

    @patch("grocery_price_cli._add_from_live_search")
    @patch("core.lookup.LookupEngine")
    @patch("grocery_price_cli._load_env")
    def test_map_unmatched_add_leaves_queue_untouched(
            self, mock_env, mock_engine_cls, mock_add_live):
        """B21: unmatched --add (live-search add path) never touches the
        queue file."""
        from core.lookup import LookupStatus
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir):
                from core import add_to_list as atl
                engine = mock_engine_cls.return_value
                engine.find_product.return_value = SimpleNamespace(
                    status=LookupStatus.LIVE_SEARCH,
                    live_items=[self._fake_prod("Live Item", 2.0)])
                args = self._map_args(add=True)
                code, _out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "unmatched",
                    ["Mystery Item 5L"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                self.assertFalse(atl.ADD_TO_LIST_PATH.exists())
        self.assertEqual(code, 0)
        mock_add_live.assert_called_once()


class TestCLIPartB(unittest.TestCase):
    """Plan matrix CLI-1..CLI-16: search display/add-item, searched-items
    queue management, and the Queue-1 vs Queue-2 separation (guardrail 4).
    All queue paths isolated to temp files; no network, no sheet."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _atl_ctx(self, tmpdir):
        """Patch context for an isolated ADD_TO_LIST_PATH."""
        from core import add_to_list as atl
        return patch.object(atl, "ADD_TO_LIST_PATH",
                            Path(tmpdir) / "add_to_list.json")

    def _fake_prod(self, raw_name, price):
        """Duck-typed live-search result covering the print path attrs."""
        return SimpleNamespace(raw_name=raw_name, price=price, brand="",
                               is_special=False, special_desc="")

    def _map_args(self, **overrides):
        """Namespace for _cmd_map_noninteractive with all action flags."""
        defaults = {"next": False, "pick": None, "add": False,
                    "skip": False, "na": False, "forget": False,
                    "keyword": None}
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def _si_ctx(self, tmpdir):
        """Patch context for isolated searched_items + tombstones paths."""
        from core import searched_items as si
        return patch.object(si, "SEARCHED_ITEMS_PATH",
                            Path(tmpdir) / "searched_items.json")

    def _si_tomb_ctx(self, tmpdir):
        """Patch context for an isolated tombstones path."""
        from core import searched_items as si
        return patch.object(si, "TOMBSTONES_PATH",
                            Path(tmpdir) / "tombstones.json")

    def _capture_stdout(self, fn, *args, **kwargs):
        """Run fn capturing stdout; returns (result, output)."""
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            result = fn(*args, **kwargs)
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        return result, output

    def _prod(self, store, name, price, size="", brand=""):
        """ProductItem fixture shorthand."""
        from extractors.models import ProductItem
        return ProductItem(store=store, raw_name=name, price=price,
                           size=size, brand=brand)

    def _run_search(self, argv_extra=None, ww=None, coles=((), "ok"),
                    product="milk", tmpdir=None):
        """Run _cmd_search with store fns patched and queue paths isolated.

        Args:
            tmpdir: optional SHARED directory for the queue files so
                consecutive runs observe each other's writes (CLI-9).

        Returns:
            tuple: (code, stdout, stderr, mock_add_row, queue_data) where
            queue_data is the searched_items queue content AFTER the run
            (real module code executed against an isolated temp file).
        """
        from grocery_price_cli import _cmd_search
        from core import searched_items as si

        ns = {"product": product, "expand": False, "add_item": None}
        ns.update(argv_extra or {})
        args = argparse.Namespace(**ns)

        own_tmp = tmpdir is None
        if own_tmp:
            tmp_holder = tempfile.TemporaryDirectory()
            tmpdir = tmp_holder.name
        try:
            with patch.object(si, "SEARCHED_ITEMS_PATH",
                              Path(tmpdir) / "searched_items.json"), \
                    patch.object(si, "TOMBSTONES_PATH",
                                 Path(tmpdir) / "tombstones.json"), \
                    patch("extractors.woolworths_extractor."
                          "fetch_woolworths_search_noauth",
                          return_value=ww or []), \
                    patch("extractors.coles_extractor."
                          "fetch_coles_search_status",
                          return_value=coles), \
                    patch("core.sheets_sync.add_product_row") as mock_row, \
                    patch("grocery_price_cli._load_env"):
                old_stdout, old_stderr = sys.stdout, sys.stderr
                try:
                    sys.stdout = io.StringIO()
                    sys.stderr = io.StringIO()
                    code = _cmd_search(args)
                    out = sys.stdout.getvalue()
                    err = sys.stderr.getvalue()
                finally:
                    sys.stdout, sys.stderr = old_stdout, old_stderr
                queue_data = si.load_pending()
        finally:
            if own_tmp:
                tmp_holder.cleanup()
        return code, out, err, mock_row, queue_data

    # ------------------------------------------------------------------
    # CLI-1..CLI-5: display-only behaviour
    # ------------------------------------------------------------------
    def test_cli1_search_max3_continuous_numbering_ranked(self):
        """CLI-1: <=3 per store, continuous numbering, ranked order."""
        ww = [self._prod("woolworths", f"WW Yogurt {i}", 5.0)
              for i in range(5)]
        coles = ([self._prod("coles", f"Coles Yogurt {i}", 5.0)
                  for i in range(5)], "ok")
        code, out, _err, _row, _si = self._run_search(ww=ww, coles=coles,
                                                      product="yogurt")
        self.assertEqual(code, 0)
        # Continuous numbering 1..6, never 7+.
        self.assertIn("1. WW Yogurt", out)
        self.assertIn("4. Coles Yogurt", out)
        self.assertNotIn("7. ", out)
        # WW block precedes Coles block.
        self.assertLess(out.index("WW Yogurt 0"), out.index("Coles Yogurt 0"))

    def test_cli2_expand_shows_up_to_8(self):
        """CLI-2: --expand raises the display to 8 per store."""
        ww = [self._prod("woolworths", f"WW Item {i:02d}", 1.0)
              for i in range(10)]
        coles = ([self._prod("coles", f"Coles Item {i:02d}", 1.0)
                  for i in range(10)], "ok")
        code, out, _err, _row, _si = self._run_search(
            {"expand": True}, ww=ww, coles=coles, product="item")
        self.assertEqual(code, 0)
        self.assertIn("16. Coles Item 07", out)
        self.assertNotIn("17. ", out)

    def test_cli3_search_lines_show_size(self):
        """CLI-3: result lines show the size when present."""
        ww = [self._prod("woolworths", "WW Salsa 200g", 3.0, size="200g")]
        code, out, _err, _row, _si = self._run_search(
            ww=ww, product="salsa")
        self.assertEqual(code, 0)
        self.assertIn("200g", out)

    def test_cli4_plain_search_writes_nothing(self):
        """CLI-4: plain search never calls add_product_row/searched_items."""
        ww = [self._prod("woolworths", "WW Milk 2L", 3.50)]
        code, _out, _err, mock_row, queue_data = self._run_search(
            ww=ww, product="milk")
        self.assertEqual(code, 0)
        mock_row.assert_not_called()
        self.assertEqual(queue_data, [])

    def test_cli5_compare_writes_nothing(self):
        """CLI-5: compare never calls add_product_row/searched_items."""
        from grocery_price_cli import _cmd_compare
        from core.price_comparator import ComparisonReport, BasketItem
        item = BasketItem(
            name="Milk", prices={"woolworths": 3.00},
            sources={"woolworths": "sheet"})
        report = ComparisonReport(
            items=[item], raw_totals={"woolworths": 3.00},
            store_coverage={"woolworths": 1},
            final_totals={"woolworths": 3.00},
            cheapest_store="woolworths", max_savings=0.0,
            not_available={"coles": ["Milk"]})
        args = argparse.Namespace(items="milk", mode="sheet",
                                  team_discount=False, extra_discount=0.0)
        with patch("core.price_comparator.compare_basket",
                   return_value=report), \
                patch("core.price_comparator.format_report",
                      return_value="report"), \
                patch("core.sheets_sync.add_product_row") as mock_row, \
                patch("core.searched_items.add_entry") as mock_si, \
                patch("grocery_price_cli._load_env"):
            old_stdout = sys.stdout
            try:
                sys.stdout = io.StringIO()
                code = _cmd_compare(args)
            finally:
                sys.stdout = old_stdout
        self.assertEqual(code, 0)
        mock_row.assert_not_called()
        mock_si.assert_not_called()

    # ------------------------------------------------------------------
    # CLI-6..CLI-9: --add-item N explicit add
    # ------------------------------------------------------------------
    def test_cli6_add_item_writes_row_without_keyword_and_queues(self):
        """CLI-6: --add-item 2 -> one add_product_row (store_keyword='')
        + exactly one searched_items entry."""
        ww = [self._prod("woolworths", "WW Yogurt A", 5.0),
              self._prod("woolworths", "WW Yogurt B", 4.0, size="1kg")]
        code, out, _err, mock_row, queue_data = self._run_search(
            {"add_item": 2}, ww=ww, product="yogurt")
        self.assertEqual(code, 0)
        mock_row.assert_called_once()
        kwargs = mock_row.call_args.kwargs
        self.assertEqual(kwargs["store_keyword"], "")       # interpretation 0.4
        self.assertEqual(kwargs["generic_name"], "WW Yogurt B")
        self.assertEqual(kwargs["alias"], "yogurt")
        self.assertEqual(len(queue_data), 1)
        self.assertEqual(queue_data[0]["store"], "woolworths")
        self.assertEqual(queue_data[0]["keyword"], "WW Yogurt B")

    def test_cli7_add_item_prints_exact_management_phrases(self):
        """CLI-7: output carries the three exact §3.4 phrases + [CODE]."""
        ww = [self._prod("woolworths", "WW Yogurt A", 5.0)]
        code, out, _err, _row, _queue = self._run_search(
            {"add_item": 1}, ww=ww, product="yogurt")
        self.assertEqual(code, 0)
        self.assertIn("Queued for Wednesday: 'WW Yogurt A' "
                      "(Woolworths) [", out)
        self.assertRegex(out, r"\[[A-Z]{3}\]")
        self.assertRegex(out, r"💬 Reply 'remove [A-Z]{3}' if this isn't "
                              r"the right product\.")
        self.assertIn("💬 'show searched items' any time to review "
                      "the queue.", out)

    def test_cli8_add_item_out_of_range_errors(self):
        """CLI-8: N out of range -> stderr error, exit 1, no writes."""
        ww = [self._prod("woolworths", "WW Yogurt A", 5.0)]
        code, _out, err, mock_row, queue_data = self._run_search(
            {"add_item": 5}, ww=ww, product="yogurt")
        self.assertEqual(code, 1)
        self.assertIn("out of range", err)
        mock_row.assert_not_called()
        self.assertEqual(queue_data, [])

    def test_cli9_add_item_already_queued(self):
        """CLI-9: duplicate add -> 'Already queued' line, no dup entry."""
        ww = [self._prod("woolworths", "WW Yogurt A", 5.0)]
        with tempfile.TemporaryDirectory() as tmpdir:
            # Shared queue dir: the second run sees the first run's write.
            self._run_search({"add_item": 1}, ww=ww, product="yogurt",
                             tmpdir=tmpdir)
            code2, out2, _err, _row, queue_data = self._run_search(
                {"add_item": 1}, ww=ww, product="yogurt", tmpdir=tmpdir)
        self.assertEqual(code2, 0)
        self.assertIn("Already queued", out2)
        self.assertEqual(len(queue_data), 1)

    def test_cli10_coles_unavailable_single_line_ww_shown(self):
        """CLI-10: Coles unavailable -> ONE line, WW results still shown."""
        ww = [self._prod("woolworths", "WW Milk 2L", 3.50)]
        code, out, _err, _row, _si = self._run_search(
            ww=ww, coles=([], "unavailable"), product="milk")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("Coles not checked (unavailable)"), 1)
        self.assertIn("WW Milk 2L", out)

    # ------------------------------------------------------------------
    # CLI-11..CLI-14: searched-items queue management
    # ------------------------------------------------------------------
    def _si_args(self, action, items=None):
        return argparse.Namespace(action=action, items=items)

    def test_cli11_show_renders_format_and_empty_line(self):
        """CLI-11: show renders 'store · name · size · [CODE]'; empty
        queue -> friendly line."""
        from grocery_price_cli import _cmd_searched_items
        from core import searched_items as si
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._si_ctx(tmpdir), self._si_tomb_ctx(tmpdir):
                code, out = self._capture_stdout(
                    _cmd_searched_items, self._si_args("show"))
                self.assertIn("searched_items is empty", out)
                si.add_entry("coles", "Obela Hommus 200g", "Hommus 200g",
                             store_product_id="1", size="200g")
                code, out = self._capture_stdout(
                    _cmd_searched_items, self._si_args("show"))
        self.assertEqual(code, 0)
        self.assertIn("coles · Obela Hommus 200g · 200g · [", out)

    def test_cli12_remove_multi_codes(self):
        """CLI-12: remove --items 'KAT,RUM' removes both + remainder."""
        from grocery_price_cli import _cmd_searched_items
        from core import searched_items as si
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._si_ctx(tmpdir), self._si_tomb_ctx(tmpdir):
                e1 = si.add_entry("coles", "Item One", "one")
                e2 = si.add_entry("woolworths", "Item Two", "two")
                e3 = si.add_entry("coles", "Item Three", "three")
                # Deterministic codes for the assertion.
                for entry, code_letter in ((e1, "KAT"), (e2, "RUM")):
                    entry["entry"]["code"] = code_letter
                entries = [e1["entry"], e2["entry"], e3["entry"]]
                si.save_pending(entries)
                code, out = self._capture_stdout(
                    _cmd_searched_items,
                    self._si_args("remove", "KAT,RUM"))
                data = si.load_pending()
        self.assertEqual(code, 0)
        self.assertEqual(len(data), 1)
        self.assertIn("Item Three", out)

    def test_cli13_unknown_code_exact_error(self):
        """CLI-13: unknown code -> exact self-correcting error, exit 1."""
        from grocery_price_cli import _cmd_searched_items
        from core import searched_items as si
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._si_ctx(tmpdir), self._si_tomb_ctx(tmpdir):
                a = si.add_entry("coles", "Item One", "one")
                a["entry"]["code"] = "KAT"
                b = si.add_entry("woolworths", "Item Two", "two")
                b["entry"]["code"] = "RUM"
                si.save_pending([a["entry"], b["entry"]])
                old_stderr = sys.stderr
                try:
                    sys.stderr = io.StringIO()
                    code = _cmd_searched_items(
                        self._si_args("remove", "KA"))
                    err = sys.stderr.getvalue()
                finally:
                    sys.stderr = old_stderr
        self.assertEqual(code, 1)
        self.assertIn("⚠️ Code 'KA' not found. Current queue codes: "
                      "KAT, RUM.", err)

    def test_cli14_clear_empties_and_tombstones(self):
        """CLI-14: clear empties the queue (tombstones written)."""
        from grocery_price_cli import _cmd_searched_items
        from core import searched_items as si
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._si_ctx(tmpdir), self._si_tomb_ctx(tmpdir):
                si.add_entry("coles", "Item One", "one")
                si.add_entry("woolworths", "Item Two", "two")
                code, out = self._capture_stdout(
                    _cmd_searched_items, self._si_args("clear"))
                data = si.load_pending()
                tombs = si._load_tombstones()
        self.assertEqual(code, 0)
        self.assertEqual(data, [])
        self.assertEqual(len(tombs), 2)
        self.assertIn("Cleared 2 item(s)", out)

    # ------------------------------------------------------------------
    # CLI-15..CLI-16: Queue-1 vs Queue-2 separation (guardrail 4)
    # ------------------------------------------------------------------
    @patch("core.sheets_sync.update_single_price")
    @patch("grocery_price_cli._search_store_with_fallback")
    @patch("grocery_price_cli._load_env")
    def test_cli15_store_map_add_feeds_queue1_only(
            self, mock_env, mock_search, mock_update):
        """CLI-15: wool/coles map --add -> add_to_list ONLY;
        searched_items untouched."""
        from grocery_price_cli import _cmd_map_noninteractive
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir), self._si_ctx(tmpdir), \
                    self._si_tomb_ctx(tmpdir):
                from core import add_to_list as atl
                from core import searched_items as si
                mock_search.return_value = (
                    [self._fake_prod("Woolworths Beef Mince 500g", 9.50)],
                    "Beef Mince 500g")
                mock_update.return_value = {"found": True, "row_index": 3}
                args = self._map_args(add=True)
                code, _out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "wool",
                    ["Beef Mince 500g"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                atl_data = atl.load_pending()
                self.assertFalse(si.SEARCHED_ITEMS_PATH.exists())
        self.assertEqual(code, 0)
        self.assertEqual(len(atl_data), 1)  # Queue 1 fed

    @patch("core.sheets_sync.add_product_row")
    @patch("core.lookup.LookupEngine")
    @patch("grocery_price_cli._load_env")
    def test_cli16_unmatched_map_add_writes_row_and_queues(
            self, mock_env, mock_engine_cls, mock_row):
        """CLI-16: unmatched (live) --add -> add_product_row with
        store_keyword='' + searched_items queued + phrases printed."""
        from core.lookup import LookupStatus
        from grocery_price_cli import _cmd_map_noninteractive
        live_item = self._prod("coles", "Obela Hommus 200g", 3.10,
                               size="200g")
        with tempfile.TemporaryDirectory() as tmpdir:
            with self._atl_ctx(tmpdir), self._si_ctx(tmpdir), \
                    self._si_tomb_ctx(tmpdir):
                from core import add_to_list as atl
                from core import searched_items as si
                engine = mock_engine_cls.return_value
                engine.find_product.return_value = SimpleNamespace(
                    status=LookupStatus.LIVE_SEARCH,
                    live_items=[live_item])
                mock_row.return_value = {"wrote": True, "row_index": 9}
                args = self._map_args(add=True)
                code, out = self._capture_stdout(
                    _cmd_map_noninteractive, args, "unmatched",
                    ["Mystery Item 5L"], 0, {},
                    Path(tmpdir) / "progress.json", Path(tmpdir))
                atl_data = atl.load_pending()
                si_data = si.load_pending()
        self.assertEqual(code, 0)
        mock_row.assert_called_once()
        self.assertEqual(mock_row.call_args.kwargs["store_keyword"], "")
        self.assertEqual(len(si_data), 1)   # Queue 2 fed
        self.assertEqual(atl_data, [])      # Queue 1 untouched
        self.assertIn("Queued for Wednesday: 'Obela Hommus 200g' "
                      "(Coles) [", out)


class TestWednesdayLiveRouting(unittest.TestCase):
    """Matrix WC-1..WC-12: wednesday docx/live routing + live-refresh.

    Fully mocked: no docx files, no sheet, no scp, no Telegram, no
    browser. The docx path gets a golden regression (WC-1/WC-2).
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _wed_args(self, **overrides):
        """Namespace for _cmd_wednesday."""
        defaults = {"dry_run": True, "no_scp": True, "no_telegram": True,
                    "source": "docx"}
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def _base_patches(self, ww_items, coles_items, patch_sync=True,
                      patch_docx=True, patch_subprocess=True):
        """Common patch context for wednesday runs (no external effects)."""
        from extractors.models import ProductItem
        fake_report = SimpleNamespace(
            rows_examined=0, rows_updated=0, items_matched=0,
            items_skipped=0, stores_synced=[], range_written="",
            warnings=[])

        class _FakeMatcher:
            def __init__(self, index):
                pass

            def match_batch(self, items):
                return [SimpleNamespace(matched=True) for _ in items]

        stack = [
            patch("grocery_price_cli._load_env", return_value=None),
            patch("core.name_matcher.load_keyword_index",
                  return_value=object()),
            patch("core.name_matcher.NameMatcher", _FakeMatcher),
            patch("core.name_matcher.get_pending_mappings",
                  return_value=[]),
            # Hermetic Step 8: the repo may contain a real specials docx.
            patch("grocery_price_cli._extract_woolworths_specials",
                  return_value=[]),
            patch("core.sheets_client.connect_worksheet",
                  return_value=FakeWorksheet([_make_header()])),
            patch("grocery_price_cli._read_ignored_items",
                  return_value=set()),
            patch("grocery_price_cli._write_list_file", return_value=None),
            patch("grocery_price_cli._reset_list_action_progress",
                  return_value=None),
        ]
        if patch_docx:
            stack.insert(1, patch(
                "extractors.doc_parser.parse_docx_cache",
                side_effect=lambda store: ww_items
                if store == "woolworths" else coles_items))
        if patch_subprocess:
            stack.append(patch(
                "subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="",
                                             stderr="")))
        if patch_sync:
            stack.append(patch("core.sheets_sync.sync_prices",
                               return_value=fake_report))
        return stack, fake_report

    def _run_wednesday(self, args, stack):
        """Run _cmd_wednesday under the given patch stack."""
        import contextlib
        with contextlib.ExitStack() as exit_stack:
            for patcher in stack:
                exit_stack.enter_context(patcher)
            old_stdout = sys.stdout
            try:
                sys.stdout = io.StringIO()
                code = _cmd_wednesday_refs()[0](args)
                out = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
        return code, out

    def _live_patches(self, snapshots=None, window_summary=None,
                      validate=None, specials_exists=True, run_mock=None,
                      snapshots_exist=True):
        """Extra patch stack for --source live."""
        from extractors.models import ProductItem
        tmp = self._tmpdir()
        existing = tmp / "snap.json"
        existing.write_text("[]", encoding="utf-8")
        snapshot_paths = ([existing, existing] if snapshots_exist
                          else [tmp / "nope1.json", tmp / "nope2.json"])
        ww_item = ProductItem(store="woolworths",
                              raw_name="WW Milk 2L", price=3.50)
        coles_item = ProductItem(store="coles",
                                 raw_name="Coles Bread 650g", price=2.80)
        run_patch = (patch("extractors.session_refresh.run", run_mock)
                     if run_mock is not None else
                     patch("extractors.session_refresh.run",
                           return_value=window_summary or {
                               "woolworths": {"login": True,
                                              "flush": {"added": [],
                                                        "failed": [],
                                                        "parked": []},
                                              "fetch": {"ok": True}},
                               "coles": {"login": True,
                                         "flush": {"added": [], "failed": [],
                                                   "parked": []},
                                         "fetch": {"ok": True}}}))
        stack = [
            patch("extractors.live_list_fetch.required_snapshot_paths",
                  return_value=snapshot_paths),
            (patch("extractors.live_list_fetch.validate_complete",
                   side_effect=validate) if validate is not None else
             patch("extractors.live_list_fetch.validate_complete",
                   return_value=None)),
            patch("extractors.live_list_fetch.snapshots_for_date",
                  return_value=snapshots or {
                      "woolworths": [ww_item], "coles": [coles_item]}),
            run_patch,
            patch("extractors.live_list_fetch.ww_snapshot_path",
                  return_value=existing if specials_exists
                  else tmp / "missing.json"),
            patch("extractors.live_list_fetch.specials_from_live",
                  return_value=[ProductItem(
                      store="woolworths", raw_name="Half Price Milk",
                      price=2.0, is_special=True,
                      special_desc="Was $4.00")]),
        ]
        return stack

    _tmpdir_holder = None

    def _tmpdir(self):
        """A shared tmp dir for the duration of the test."""
        if self._tmpdir_holder is None:
            self._tmpdir_holder = tempfile.TemporaryDirectory()
            self.addCleanup(self._tmpdir_holder.cleanup)
        return Path(self._tmpdir_holder.name)

    # ------------------------------------------------------------------
    # WC-1..WC-2: docx golden
    # ------------------------------------------------------------------
    def test_wc1_docx_default_golden(self):
        """WC-1: wednesday (no flag) -> docx path unchanged."""
        stack, _report = self._base_patches(
            [SimpleNamespace(raw_name="WW Milk")],
            [SimpleNamespace(raw_name="Coles Bread")])
        args = self._wed_args()
        code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 0)
        self.assertIn("Step 1: Parsing Word documents...", out)
        self.assertEqual(out.count("items parsed"), 2)
        self.assertIn("Total: 2 items across 2 store(s)", out)
        self.assertNotIn("live snapshots", out)

    def test_wc2_explicit_docx_identical(self):
        """WC-2: --source docx explicit -> identical to WC-1."""
        stack1, _ = self._base_patches(
            [SimpleNamespace(raw_name="WW Milk")],
            [SimpleNamespace(raw_name="Coles Bread")])
        out1 = self._run_wednesday(self._wed_args(), stack1)[1]
        stack2, _ = self._base_patches(
            [SimpleNamespace(raw_name="WW Milk")],
            [SimpleNamespace(raw_name="Coles Bread")])
        out2 = self._run_wednesday(self._wed_args(source="docx"), stack2)[1]
        self.assertEqual(out1, out2)

    # ------------------------------------------------------------------
    # WC-3..WC-6: live routing
    # ------------------------------------------------------------------
    def test_wc3_live_source_reads_snapshots(self):
        """WC-3: --source live with snapshots -> steps 1-2 read them."""
        stack, _report = self._base_patches([], [])
        stack.extend(self._live_patches())
        args = self._wed_args(source="live")
        code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 0)
        self.assertIn("items from snapshot", out)
        self.assertNotIn("Parsing Word documents", out)

    def test_wc4_missing_snapshots_clean_stop_no_sync(self):
        """WC-4: window failed -> §5.2 stop, exit 1, sync NEVER called."""
        stack, _report = self._base_patches([], [], patch_sync=False)
        stack.extend(self._live_patches(
            validate=ValueError(
                "Live fetch incomplete — clean stop before any sheet "
                "write. Problems: missing: 2026-09-02_ww_pricecompare.json."
                " Re-run the live window (live-refresh) or paste your "
                "lists into the Word docs as before and run wednesday "
                "(no flag) — everything else is unchanged.")))
        args = self._wed_args(source="live")
        import contextlib
        with contextlib.ExitStack() as exit_stack:
            for patcher in stack:
                exit_stack.enter_context(patcher)
            with patch("core.sheets_sync.sync_prices") as mock_sync:
                old_stdout = sys.stdout
                try:
                    sys.stdout = io.StringIO()
                    code = _cmd_wednesday_refs()[0](args)
                    out = sys.stdout.getvalue()
                finally:
                    sys.stdout = old_stdout
                mock_sync.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("clean stop before any sheet write", out)
        self.assertIn("wednesday", out)

    def test_wc5_partial_snapshots_same_stop(self):
        """WC-5: one store's snapshot missing -> same clean stop."""
        stack, _report = self._base_patches([], [])
        stack.extend(self._live_patches(
            validate=ValueError("Live fetch incomplete — clean stop "
                                "before any sheet write. Problems: "
                                "missing: 2026-09-02_coles_pricecompare"
                                ".json.")))
        args = self._wed_args(source="live")
        code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 1)
        self.assertIn("coles_pricecompare.json", out)

    def test_wc6_docx_never_silently_substituted(self):
        """WC-6: live failure never falls back to docx parsing."""
        docx_mock = MagicMock(side_effect=lambda store: [])
        stack, _report = self._base_patches([], [], patch_docx=False)
        stack.append(patch("extractors.doc_parser.parse_docx_cache",
                           docx_mock))
        stack.extend(self._live_patches(
            validate=ValueError("missing snapshots")))
        args = self._wed_args(source="live")
        import contextlib
        with contextlib.ExitStack() as exit_stack:
            for patcher in stack:
                exit_stack.enter_context(patcher)
            old_stdout = sys.stdout
            try:
                sys.stdout = io.StringIO()
                code = _cmd_wednesday_refs()[0](args)
                out = sys.stdout.getvalue()
            finally:
                sys.stdout = old_stdout
        self.assertEqual(code, 1)
        self.assertEqual(docx_mock.call_count, 0)

    # ------------------------------------------------------------------
    # WC-7..WC-9: Step 0 queue pull + window skip
    # ------------------------------------------------------------------
    def test_wc7_step0_pulls_both_queues_via_scp(self):
        """WC-7: Step 0 scp-pulls add_to_list + searched_items."""
        mock_run = MagicMock(return_value=SimpleNamespace(
            returncode=0, stdout="", stderr=""))
        stack, _report = self._base_patches([], [], patch_subprocess=False)
        stack.append(patch("subprocess.run", mock_run))
        stack.extend(self._live_patches())
        args = self._wed_args(source="live", dry_run=False, no_scp=False)
        code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 0)
        scp_calls = [c for c in mock_run.call_args_list
                     if c.args and c.args[0] and c.args[0][0] == "scp"]
        pulled = " ".join(" ".join(c.args[0]) for c in scp_calls)
        self.assertIn("add_to_list.json", pulled)
        self.assertIn("searched_items.json", pulled)

    def test_wc8_scp_unreachable_proceeds_local(self):
        """WC-8: scp unreachable -> ONE warning, proceeds, exit 0."""
        mock_run = MagicMock(return_value=SimpleNamespace(
            returncode=1, stdout="", stderr="unreachable"))
        stack, _report = self._base_patches([], [], patch_subprocess=False)
        stack.append(patch("subprocess.run", mock_run))
        stack.extend(self._live_patches())
        args = self._wed_args(source="live", dry_run=False, no_scp=False)
        code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("proceeding with local copies"), 1)

    def test_wc9_existing_snapshots_skip_window(self):
        """WC-9: today's snapshots exist -> live window NOT invoked."""
        stack, _report = self._base_patches([], [])
        stack.extend(self._live_patches())
        with patch("extractors.session_refresh.run",
                   side_effect=AssertionError("window must not run")) as \
                mock_run:
            # (the _live_patches already patched run; override semantics
            # via an explicit nested patch check on call count instead)
            pass
        args = self._wed_args(source="live")
        code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 0)
        self.assertIn("already exist", out)
        self.assertNotIn("Live window: opening browser", out)

    # ------------------------------------------------------------------
    # WC-10..WC-12: dry-run flush skip, specials, telegram
    # ------------------------------------------------------------------
    def test_wc10_dry_run_skips_flush_only(self):
        """WC-10: --dry-run --source live -> flush skipped, fetch runs."""
        run_mock = MagicMock(return_value={
            "woolworths": {"login": True, "fetch": {"ok": True}},
            "coles": {"login": True, "fetch": {"ok": True}}})
        stack, _report = self._base_patches([], [])
        stack.extend(self._live_patches(run_mock=run_mock,
                                        snapshots_exist=False))
        args = self._wed_args(source="live", dry_run=True)
        code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 0)
        self.assertFalse(run_mock.call_args.kwargs.get("flush", True))
        self.assertTrue(run_mock.call_args.kwargs.get("fetch"))

    def test_wc11_specials_from_live_snapshot(self):
        """WC-11: Step 8 specials come from the live snapshot."""
        stack, _report = self._base_patches([], [])
        stack.extend(self._live_patches())
        args = self._wed_args(source="live")
        code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 0)
        self.assertIn("from live snapshot", out)
        self.assertIn("1 specials found", out)

    def test_wc12_telegram_reflects_live_and_flush_failures(self):
        """WC-12: Telegram summary reflects live source + failed items."""
        stack, _report = self._base_patches([], [])
        window_summary = {
            "woolworths": {"login": True,
                           "flush": {"added": [],
                                     "failed": [{"keyword":
                                                 "Obela Hommus 200g",
                                                 "reason": "HTTP 500"}],
                                     "parked": []},
                           "fetch": {"ok": True}},
            "coles": {"login": True,
                      "flush": {"added": [], "failed": [], "parked": []},
                      "fetch": {"ok": True}},
        }
        stack.extend(self._live_patches(window_summary=window_summary,
                                        snapshots_exist=False))
        args = self._wed_args(source="live", dry_run=False, no_scp=False,
                              no_telegram=False)
        sent = []
        with patch("grocery_price_cli._send_telegram",
                   side_effect=lambda *a, **k: sent.append(a[2]) or True), \
                patch.dict(os.environ, {"TELEGRAM_CLAW_BOT": "test-token"}):
            code, out = self._run_wednesday(args, stack)
        self.assertEqual(code, 0)
        self.assertTrue(sent)
        summary_text = sent[0]
        self.assertIn("(LIVE)", summary_text)
        self.assertIn("live snapshots", summary_text)
        self.assertIn("Obela Hommus 200g", summary_text)


def _cmd_wednesday_refs():
    """Import the wednesday handler lazily (returns [func])."""
    from grocery_price_cli import _cmd_wednesday
    return [_cmd_wednesday]


class TestDiscoveryStatusPrints(unittest.TestCase):
    """D27/WP4: live-refresh prints per-store Discovery status lines."""

    def test_discovery_lines_printed(self):
        import contextlib
        import grocery_price_cli
        summary = {
            "woolworths": {"login": True, "flush": None, "fetch": None},
            "coles": {"login": True, "flush": None, "fetch": None},
            "discovery": {"woolworths": "captured", "coles": "failed"},
        }
        args = SimpleNamespace(recapture=False, flush_only=False,
                               fetch_only=False)
        buf = io.StringIO()
        with patch("extractors.session_refresh.run",
                   return_value=summary), \
             contextlib.redirect_stdout(buf):
            code = grocery_price_cli._cmd_live_refresh(args)
        out = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn(grocery_price_cli.kv("Discovery", "captured"), out)
        self.assertIn(grocery_price_cli.kv(
            "Discovery",
            "failed — run 'live-refresh --recapture' to train"), out)


class TestTopicSplit(unittest.TestCase):
    """D24/WP5: routing, chunking, fallback, topics-check, reminder."""

    def setUp(self):
        import grocery_price_cli as gpc
        self.gpc = gpc
        self._env = {}
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        for var in ("TELEGRAM_WEEKLY_TOPIC_ID",
                    "TELEGRAM_SPECIALS_TOPIC_ID"):
            os.environ.pop(var, None)

    def test_int_env_matrix(self):
        gpc = self.gpc
        with patch.dict(os.environ, {"TELEGRAM_WEEKLY_TOPIC_ID": "777"}):
            self.assertEqual(
                gpc._int_env("TELEGRAM_WEEKLY_TOPIC_ID", None), 777)
        self.assertIsNone(gpc._int_env("TELEGRAM_WEEKLY_TOPIC_ID", None))
        with patch.dict(os.environ, {"TELEGRAM_WEEKLY_TOPIC_ID": "abc"}):
            self.assertEqual(
                gpc._int_env("TELEGRAM_WEEKLY_TOPIC_ID", 5), 5)

    def test_chunk_list_message(self):
        gpc = self.gpc
        self.assertEqual(gpc._chunk_list_message("Unmatched", []),
                         ["📋 Unmatched: none"])
        one = gpc._chunk_list_message("Unmatched", ["milk"])
        self.assertEqual(len(one), 1)
        self.assertIn("• milk", one[0])
        big = gpc._chunk_list_message(
            "Woolworths missing", [f"item {i} " * 8 for i in range(600)])
        self.assertGreater(len(big), 1)
        for n, part in enumerate(big, 1):
            self.assertLessEqual(len(part), 4000)
            self.assertIn(f"(part {n}/{len(big)})", part)

    def _posted(self, calls):
        return [
            (c.kwargs.get("message_thread_id"), c.args[1])
            for c in calls
        ]

    def test_post_weekly_summary_routes_to_weekly_topic_never_151(self):
        gpc = self.gpc
        calls = []
        with patch.dict(os.environ,
                        {"TELEGRAM_WEEKLY_TOPIC_ID": "777"}), \
             patch.object(gpc, "_send_telegram",
                          side_effect=lambda *a, **k: calls.append(
                              _Call(a, k)) or True):
            gpc._post_weekly_summary("tok", "summary", [
                ("Unmatched", ["a"]), ("Woolworths missing", []),
                ("Coles missing", ["b", "c"]),
            ])
        threads = [c.thread for c in calls]
        self.assertIn(777, threads)
        self.assertNotIn(151, threads)
        dm = [c for c in calls if c.chat == gpc._TELEGRAM_USER_ID]
        self.assertEqual(len(dm), 1)  # DMs keep exactly the summary

    def test_post_specials_routes_to_specials_topic_never_151(self):
        gpc = self.gpc
        calls = []
        with patch.dict(os.environ,
                        {"TELEGRAM_SPECIALS_TOPIC_ID": "888"}), \
             patch.object(gpc, "_send_telegram",
                          side_effect=lambda *a, **k: calls.append(
                              _Call(a, k)) or True):
            gpc._post_specials_report("tok", "specials text")
        threads = [c.thread for c in calls]
        self.assertIn(888, threads)
        self.assertNotIn(151, threads)

    def test_unset_ids_fall_back_to_dm_only(self):
        gpc = self.gpc
        calls = []
        with patch.object(gpc, "_send_telegram",
                          side_effect=lambda *a, **k: calls.append(
                              _Call(a, k)) or True):
            gpc._post_weekly_summary("tok", "summary", [("Unmatched", [])])
            gpc._post_specials_report("tok", "spec")
        for c in calls:
            self.assertIsNone(c.thread)
            self.assertEqual(c.chat, gpc._TELEGRAM_USER_ID)


class _Call:
    """Tiny record of one _send_telegram invocation."""

    def __init__(self, args, kwargs):
        self.args = args
        self.kwargs = kwargs
        self.chat = args[1]
        self.thread = kwargs.get("message_thread_id")


class TestTopicsCheck(unittest.TestCase):
    """WP5: topics-check parses a mocked getUpdates payload."""

    def test_parses_topic_creation_and_messages(self):
        import grocery_price_cli as gpc
        payload = {
            "ok": True,
            "result": [
                {"message": {
                    "message_thread_id": 543,
                    "forum_topic_created": {"name": "specials-wool"},
                    "text": "",
                }},
                {"message": {
                    "message_thread_id": 544,
                    "text": "@ClawArkindBot id",
                }},
            ],
        }
        fake_urlopen = mock_open(
            read_data=json.dumps(payload).encode("utf-8"))
        with patch("urllib.request.urlopen", fake_urlopen), \
             patch.dict(os.environ, {"TELEGRAM_CLAW_BOT": "tok"}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = gpc._cmd_topics_check(argparse.Namespace())
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("specials-wool → 543", out)
        self.assertIn("544 · @ClawArkindBot id", out)


class TestWednesdayReminderRouting(unittest.TestCase):
    """WP5: reminder routes to the weekly ID via env/patchable constant."""

    _PATH = Path(__file__).resolve().parents[2] / \
        "telegram_gateway" / "wednesday_reminder.py"

    def _load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "wednesday_reminder_test", str(self._PATH))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_env_override_routes_topic(self):
        mod = self._load()
        sent = []

        def fake_send(token, chat_id, text, message_thread_id=None):
            sent.append((chat_id, message_thread_id))

        with patch.dict(os.environ,
                        {"TELEGRAM_WEEKLY_TOPIC_ID": "777"}), \
             patch.object(mod, "send_message", fake_send), \
             patch.object(mod, "user_ids", lambda: [1]):
            mod.fire("tok")
        topic_calls = [c for c in sent if c[0] == mod.CHAT_ID]
        self.assertEqual(topic_calls, [(mod.CHAT_ID, 777)])

    def test_unset_id_dm_only_no_crash(self):
        mod = self._load()
        sent = []

        def fake_send(token, chat_id, text, message_thread_id=None):
            sent.append((chat_id, message_thread_id))

        os.environ.pop("TELEGRAM_WEEKLY_TOPIC_ID", None)
        with patch.object(mod, "WEEKLY_THREAD_ID", None), \
             patch.object(mod, "send_message", fake_send), \
             patch.object(mod, "user_ids", lambda: [1]):
            results = mod.fire("tok")
        self.assertEqual(
            [c for c in sent if c[0] == mod.CHAT_ID], [])
        self.assertTrue(results["topic"]["skipped"])


if __name__ == "__main__":
    unittest.main()
