#!/usr/bin/env python3
"""Pure unit tests for Phase 4 modules: recipe resolver, price comparator,
Woolworths discounts, specials reporter. No network, no live sheet."""
from __future__ import annotations
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.price_comparator import (  # noqa: E402
    BasketItem, ComparisonReport, compare_basket, format_report,
)


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
    """Parse 'A2:O83' -> (start_row, start_col, end_row, end_col). 1-based."""
    m = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
    if not m:
        raise ValueError(f"Cannot parse range: {range_name}")
    sc = _col_letter_to_idx(m.group(1))
    sr = int(m.group(2))
    ec = _col_letter_to_idx(m.group(3))
    er = int(m.group(4))
    return sr, sc, er, ec


def _col_letter_to_idx(letter: str) -> int:
    """'A'->0, 'Z'->25, 'AA'->26."""
    idx = 0
    for ch in letter:
        idx = idx * 26 + (ord(ch.upper()) - ord('A') + 1)
    return idx - 1


def _make_header(base_only: bool = False) -> list:
    """Return a standard Products_Master header (12 base cols or 15 with M/N/O)."""
    header = [
        "Product_Name", "Category", "Size", "Woolworths_Price", "Coles_Price",
        "Aldi_Price", "Brand_Type", "Last_Updated", "Search_Keyword_Woolworths",
        "Search_Keyword_Coles", "Search_Keyword_Aldi", "Aldi_Refresh",
    ]
    if not base_only:
        header.extend(["Woolworths_Specials", "Coles_Specials", "Rewards_Points"])
    return header


def _make_product_item(store: str, raw_name: str, price: float, *,
                       is_special: bool = False,
                       special_desc: str = "",
                       brand: str = "",
                       rewards_points: str = ""):
    """Build a ProductItem-compatible object for test stubs."""
    from extractors.models import ProductItem
    return ProductItem(
        store=store,
        raw_name=raw_name,
        price=price,
        is_special=is_special,
        special_desc=special_desc,
        brand=brand,
        rewards_points=rewards_points,
    )


# ============================================================================
# 18 Test Cases
# ============================================================================


class TestComparator(unittest.TestCase):
    """Tests for price_comparator, woolworths_discounts, recipe_resolver,
    and specials_reporter."""

    # ========================================================================
    # Comparator tests
    # ========================================================================

    def test_compare_empty_basket(self):
        """Empty basket returns empty report."""
        from core.price_comparator import compare_basket
        report = compare_basket("")
        self.assertEqual(report.items, [])
        self.assertIsNone(report.cheapest_store)
        self.assertEqual(report.final_totals, {})

    def test_compare_single_item_sheet_mode(self):
        """Single item with sheet prices at woolworths+coles."""
        from core.price_comparator import compare_basket
        header = _make_header()
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "$4.50", "$4.20", "",
             "Woolworths", "", "oat milk", "", "", "",
             "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        report = compare_basket("Oat Milk", mode="sheet", worksheet=ws)
        self.assertIn("woolworths", report.raw_totals)
        self.assertIn("coles", report.raw_totals)
        self.assertEqual(report.raw_totals["woolworths"], 4.50)
        self.assertEqual(report.raw_totals["coles"], 4.20)
        self.assertIsNotNone(report.cheapest_store)

    def test_compare_multi_item_sheet_mode(self):
        """Three items, correct raw_totals and store_coverage."""
        from core.price_comparator import compare_basket
        header = _make_header()
        rows = [
            header,
            ["Milk", "Dairy", "2L", "$3.00", "$2.80", "$2.90",
             "", "", "milk", "", "", "", "", "", ""],
            ["Bread", "Bakery", "650g", "$2.50", "$3.00", "",
             "", "", "bread", "", "", "", "", "", ""],
            ["Eggs", "Dairy", "12pk", "$5.00", "", "$4.80",
             "", "", "eggs", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        report = compare_basket(
            "milk, bread, eggs", mode="sheet", worksheet=ws
        )
        self.assertEqual(report.raw_totals["woolworths"], 10.50)
        self.assertEqual(report.raw_totals["coles"], 5.80)
        self.assertEqual(report.store_coverage["woolworths"], 3)
        self.assertEqual(report.store_coverage["coles"], 2)

    def test_compare_missing_price_flagged_not_available(self):
        """Item present at woolworths only — coles flagged."""
        from core.price_comparator import compare_basket
        header = _make_header()
        rows = [
            header,
            ["Milk", "Dairy", "2L", "$3.00", "", "",
             "", "", "milk", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        report = compare_basket("milk", mode="sheet", worksheet=ws)
        self.assertIn("coles", report.not_available)
        self.assertIn("milk", report.not_available["coles"])
        self.assertNotIn("coles", report.raw_totals)

    def test_base_discount_all_items_plus_home_extra(self):
        """Base 5% on ALL WW items; compounded extra 5% on home brands."""
        from core.price_comparator import compare_basket
        header = _make_header()
        rows = [
            header,
            ["Woolworths Milk", "Dairy", "2L", "$4.00", "$4.20", "",
             "Woolworths", "", "milk", "", "", "", "", "", ""],
            ["Bega Cheese", "Dairy", "500g", "$5.00", "$4.80", "",
             "Bega", "", "cheese", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        report = compare_basket(
            "woolworths milk, bega cheese", mode="sheet",
            team_discount=True, worksheet=ws,
        )
        self.assertTrue(report.team_discount_applied)
        # Base savings over ALL WW items: 0.20 (milk) + 0.25 (bega)
        self.assertAlmostEqual(report.team_discount_savings, 0.45)
        # Home-brand extra only for the Woolworths milk: 3.80 -> 3.61
        self.assertAlmostEqual(report.home_extra_savings, 0.19)
        self.assertEqual(report.home_brand_count, 1)
        # WW final total = sum of rounded per-item finals: 3.61 + 4.75
        self.assertAlmostEqual(report.final_totals["woolworths"], 8.36)
        # Coles never discounted (raw).
        self.assertAlmostEqual(report.raw_totals["coles"], 9.00)
        self.assertAlmostEqual(report.final_totals["coles"], 9.00)

    def test_team_discount_toggle_off(self):
        """team_discount=False disables ALL display discounts."""
        from core.price_comparator import compare_basket
        header = _make_header()
        rows = [
            header,
            ["Woolworths Milk", "Dairy", "2L", "$3.00", "", "",
             "Woolworths", "", "milk", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        report = compare_basket(
            "woolworths milk", mode="sheet",
            team_discount=False, worksheet=ws,
        )
        self.assertFalse(report.team_discount_applied)
        self.assertEqual(report.team_discount_savings, 0.0)
        self.assertEqual(report.home_extra_savings, 0.0)
        self.assertEqual(report.home_brand_count, 0)
        self.assertEqual(report.final_totals["woolworths"], 3.00)

    def test_master_switch_off_reverts_to_raw(self):
        """team_discount=None follows TEAM_DISCOUNT_ENABLED: switch off ->
        raw totals everywhere, no savings, final == raw."""
        from core.price_comparator import compare_basket
        from core import woolworths_discounts
        header = _make_header()
        rows = [
            header,
            ["Woolworths Milk", "Dairy", "2L", "$3.00", "", "",
             "Woolworths", "", "milk", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        with patch.object(
            woolworths_discounts, "TEAM_DISCOUNT_ENABLED", False
        ):
            report = compare_basket(
                "woolworths milk", mode="sheet", worksheet=ws,
            )
        self.assertFalse(report.team_discount_applied)
        self.assertEqual(report.team_discount_savings, 0.0)
        self.assertEqual(report.home_extra_savings, 0.0)
        self.assertEqual(report.home_brand_count, 0)
        self.assertEqual(
            report.final_totals["woolworths"],
            report.raw_totals["woolworths"],
        )
        self.assertEqual(report.final_totals["woolworths"], 3.00)

    def test_master_switch_default_on(self):
        """team_discount=None with the default switch ON behaves like the
        classic always-on path (discounts applied)."""
        from core.price_comparator import compare_basket
        header = _make_header()
        rows = [
            header,
            ["Woolworths Milk", "Dairy", "2L", "$3.00", "", "",
             "Woolworths", "", "milk", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        report = compare_basket(
            "woolworths milk", mode="sheet", worksheet=ws,
        )
        self.assertTrue(report.team_discount_applied)
        # Brand "Woolworths" -> home brand -> compounded: 3.00 -> 2.71.
        self.assertEqual(report.final_totals["woolworths"], 2.71)

    def test_extra_discount_applied_when_available(self):
        """Extra discount applied when monthly tracker is empty."""
        from core.price_comparator import compare_basket
        from core import woolworths_discounts

        # Point tracker to a temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker_path = Path(tmpdir) / "woolworths_discount_usage.json"
            with patch.object(
                woolworths_discounts, "TRACKER_PATH", tracker_path
            ):
                header = _make_header()
                rows = [
                    header,
                    # $4.00 (not $3.00): avoids float half-cent boundary —
                    # base 3.80, extra 10% of 3.80 = 0.38 exactly.
                    ["Milk", "Dairy", "2L", "$4.00", "$2.80", "",
                     "", "", "milk", "", "", "", "", "", ""],
                ]
                ws = FakeWorksheet(rows)
                report = compare_basket(
                    "milk", mode="sheet",
                    extra_discount_pct=10, worksheet=ws,
                )
                self.assertGreater(report.extra_discount_savings, 0)
                # Check tracker was written
                self.assertTrue(tracker_path.exists())
                with open(tracker_path) as f:
                    data = json.load(f)
                self.assertIn("last_used", data)

    def test_extra_discount_blocked_when_already_used(self):
        """Extra discount skipped when already used this month."""
        from core.price_comparator import compare_basket
        from core import woolworths_discounts
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker_path = Path(tmpdir) / "woolworths_discount_usage.json"
            # Pre-write tracker with current month
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo("Australia/Sydney"))
            except Exception:
                now = datetime.utcnow()
            current_month = now.strftime("%Y-%m")
            tracker_path.parent.mkdir(parents=True, exist_ok=True)
            with open(tracker_path, "w") as f:
                json.dump({"last_used": current_month, "history": []}, f)

            with patch.object(
                woolworths_discounts, "TRACKER_PATH", tracker_path
            ):
                header = _make_header()
                rows = [
                    header,
                    ["Milk", "Dairy", "2L", "$3.00", "", "",
                     "", "", "milk", "", "", "", "", "", ""],
                ]
                ws = FakeWorksheet(rows)
                report = compare_basket(
                    "milk", mode="sheet",
                    extra_discount_pct=10, worksheet=ws,
                )
                self.assertEqual(report.extra_discount_savings, 0.0)
                self.assertTrue(
                    any("already used" in w for w in report.warnings)
                )

    def test_monthly_tracker_can_use_then_block(self):
        """can_use True -> mark_used -> can_use False (same month)."""
        from core.woolworths_discounts import (
            can_use_monthly_discount,
            mark_monthly_discount_used,
            monthly_discount_summary,
            TRACKER_PATH,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker_path = Path(tmpdir) / "woolworths_discount_usage.json"
            with patch(
                "core.woolworths_discounts.TRACKER_PATH", tracker_path
            ):
                self.assertTrue(can_use_monthly_discount())
                mark_monthly_discount_used()
                self.assertFalse(can_use_monthly_discount())
                summary = monthly_discount_summary()
                self.assertFalse(summary["available"])
                self.assertEqual(summary["history_len"], 1)

    def test_is_woolworths_home_brand_labels(self):
        """Detection follows spec §4: exact brand match, Home marker,
        woolworths prefix, leading name fallback. Dropped labels
        ('gold', 'free from') must NOT match."""
        from core.woolworths_discounts import is_woolworths_home_brand

        self.assertTrue(
            is_woolworths_home_brand("Woolworths Milk", "")
        )
        self.assertTrue(
            is_woolworths_home_brand("", "Woolworths")
        )
        self.assertTrue(
            is_woolworths_home_brand("Macro Free Range Eggs", "")
        )
        self.assertTrue(
            is_woolworths_home_brand("Bananas", "The Odd Bunch")
        )
        # Dropped labels — no longer home brands.
        self.assertFalse(
            is_woolworths_home_brand("Gold Coffee", "")
        )
        self.assertFalse(
            is_woolworths_home_brand("Free From Bread", "")
        )
        self.assertFalse(
            is_woolworths_home_brand("Bega Cheese", "Bega")
        )
        self.assertFalse(is_woolworths_home_brand("", ""))

    def test_resolver_exact_sheet_match(self):
        """Query matches exact generic name in sheet."""
        from core.recipe_resolver import RecipeResolver
        header = _make_header()
        rows = [
            header,
            ["Oat Milk", "Dairy", "1L", "$4.50", "$4.20", "",
             "Oatly", "", "oat milk", "oat milk", "", "",
             "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        resolver = RecipeResolver(worksheet=ws)
        result = resolver.resolve("oat milk")
        self.assertEqual(result.source, "exact_sheet")
        self.assertEqual(result.confidence, "exact")
        self.assertEqual(result.generic_name, "Oat Milk")
        self.assertEqual(result.prices["woolworths"], 4.50)

    def test_resolver_partial_substring_match(self):
        """Query 'beef mince' matches 'Beef Mince 500g' via partial."""
        from core.recipe_resolver import RecipeResolver
        header = _make_header()
        rows = [
            header,
            # No keyword in Col I/J/K — forces fallthrough to partial matching
            ["Beef Mince 500g", "Meat", "500g", "$8.00", "$7.50", "",
             "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        resolver = RecipeResolver(worksheet=ws)
        result = resolver.resolve("beef mince")
        self.assertEqual(result.source, "partial_sheet")
        self.assertEqual(result.confidence, "partial")
        self.assertEqual(result.generic_name, "Beef Mince 500g")

    def test_resolver_live_search_fallback(self):
        """Query not in sheet falls back to live search stubs."""
        from core.recipe_resolver import RecipeResolver
        from extractors.models import ProductItem

        header = _make_header()
        rows = [header]
        ws = FakeWorksheet(rows)

        def stub_ww_search(term, page_size=5):
            return [ProductItem("woolworths", "Fresh Milk 2L", 3.50)]

        def stub_coles_search(term, page_size=5):
            return [ProductItem("coles", "Coles Milk 2L", 3.30)]

        resolver = RecipeResolver(worksheet=ws)
        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search",
            side_effect=stub_ww_search,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search",
            side_effect=stub_coles_search,
        ):
            result = resolver.resolve("milk")
        self.assertEqual(result.source, "live_search")
        self.assertEqual(result.confidence, "live")
        self.assertIn("woolworths", result.prices)
        self.assertIn("coles", result.prices)

    def test_resolver_not_found(self):
        """Unknown query returns not_found."""
        from core.recipe_resolver import RecipeResolver

        header = _make_header()
        rows = [header]
        ws = FakeWorksheet(rows)

        def stub_search(term, page_size=5):
            return []

        resolver = RecipeResolver(worksheet=ws)
        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search",
            side_effect=stub_search,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search",
            side_effect=stub_search,
        ):
            result = resolver.resolve("xyzunknown")
        self.assertEqual(result.source, "not_found")
        self.assertEqual(result.confidence, "none")
        self.assertEqual(result.prices, {})

    def test_specials_reporter_filters_active(self):
        """get_active_specials returns items with non-empty specials,
        carrying their Col G brand for discount attribution."""
        from core.specials_reporter import (
            get_active_specials, format_specials_report,
        )
        header = _make_header()
        rows = [
            header,
            ["Milk", "Dairy", "2L", "$3.00", "", "",
             "Bega", "", "milk", "", "", "",
             "Half Price", "", ""],
            ["Bread", "Bakery", "650g", "$2.50", "", "",
             "", "", "bread", "", "", "",
              "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        specials = get_active_specials(store="woolworths", worksheet=ws)
        self.assertEqual(len(specials), 1)
        self.assertEqual(specials[0]["name"], "Milk")
        self.assertEqual(specials[0]["special_desc"], "Half Price")
        # Brand resolved from the brand cell (Brand_Type fallback).
        self.assertEqual(specials[0]["brand"], "Bega")

        # WW rows display the discounted price only — NO team-discount
        # "(was $x)" suffix. Regular brand -> base 5% ($3.00 -> $2.85).
        output = format_specials_report(specials, "woolworths")
        self.assertIn("2.85", output)     # 3.00 base-discounted
        self.assertNotIn("was $3.00", output)  # no team-discount "was"
        self.assertIn("Half Price", output)    # genuine desc rides along

    def test_specials_reporter_home_brand_extra_discount(self):
        """WW home-brand special shows compounded ~9.75% discount."""
        from core.specials_reporter import (
            get_active_specials, format_specials_report,
        )
        header = _make_header()
        rows = [
            header,
            ["Odd Bunch Apples", "Produce", "1kg", "$4.00", "", "",
             "The Odd Bunch", "", "apples", "", "", "",
             "Special", "", ""],
        ]
        ws = FakeWorksheet(rows)
        specials = get_active_specials(store="woolworths", worksheet=ws)
        output = format_specials_report(specials, "woolworths")
        self.assertIn("3.61", output)      # 4.00 -> 3.80 -> 3.61
        self.assertNotIn("was $4.00", output)
        self.assertIn("Special", output)   # genuine desc rides along

    def test_bonus_rewards_carry_store_and_brand(self):
        """get_bonus_rewards records which store supplied the price."""
        from core.specials_reporter import get_bonus_rewards
        header = _make_header()
        rows = [
            header,
            ["Woolworths Milk", "Dairy", "2L", "$4.00", "$3.80", "",
             "Woolworths", "", "milk", "", "", "",
             "", "", "1000 pts"],
        ]
        ws = FakeWorksheet(rows)
        rewards = get_bonus_rewards(worksheet=ws)
        self.assertEqual(len(rewards), 1)
        r = rewards[0]
        # Price parsed from the FIRST populated store column: woolworths.
        self.assertEqual(r["store"], "woolworths")
        self.assertAlmostEqual(r["price"], 4.00)
        self.assertEqual(r["brand"], "Woolworths")

    def test_specials_reporter_missing_columns_returns_empty(self):
        """Missing M/N/O columns returns empty lists, no exception."""
        from core.specials_reporter import (
            get_active_specials, get_bonus_rewards,
        )
        header = _make_header(base_only=True)
        rows = [
            header,
            ["Milk", "", "", "", "", "", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)
        self.assertEqual(get_active_specials(worksheet=ws), [])
        self.assertEqual(get_bonus_rewards(worksheet=ws), [])

    def test_format_report_contains_discount_lines(self):
        """format_report shows the base + home-extra discount lines, the
        WW item cell with the discounted price (NO team-discount "was"
        suffix; raw only in the totals table), and cheapest store
        computed on final totals."""
        from core.price_comparator import ComparisonReport, format_report
        from core.price_comparator import BasketItem

        # $4.00 home brand: base 3.80 -> compounded final 3.61.
        item = BasketItem(
            name="Woolworths Milk",
            prices={"woolworths": 4.00, "coles": 3.20},
            sources={"woolworths": "sheet", "coles": "sheet"},
            brand="Woolworths",
            is_woolworths_home_brand=True,
        )
        report = ComparisonReport(
            items=[item],
            raw_totals={"woolworths": 4.00, "coles": 3.20},
            store_coverage={"woolworths": 1, "coles": 1},
            team_discount_applied=True,
            team_discount_savings=0.20,
            home_extra_savings=0.19,
            home_brand_count=1,
            extra_discount_pct=10.0,
            extra_discount_savings=0.36,
            final_totals={"woolworths": 3.25, "coles": 3.20},
            cheapest_store="coles",
            most_expensive_store="woolworths",
            max_savings=0.05,
            not_available={
                "woolworths": [], "coles": [],
                "aldi": ["Woolworths Milk"],
            },
        )
        output = format_report(report)
        # WW item line: discounted price prominent; NO team-discount
        # "was" bracket (raw $4.00 appears only in the totals table).
        self.assertIn("3.61", output)
        self.assertNotIn("(was $4.00)", output)
        self.assertNotIn("(Home 9.75% off", output)
        # Home-brand extra sub-block with its total.
        self.assertIn("HOME BRAND EXTRA", output)
        self.assertIn("0.19", output)
        # 🏷️ WW discounts tail: 5% base summarised with its amount.
        self.assertIn("5%", output)
        self.assertIn("0.20", output)
        # Extra discount rendered as the compact 🏷️ line.
        self.assertIn("Extra 10%", output)
        # Cheapest store announced by the 🏆 tail line.
        self.assertIn("🏆 Cheapest: Coles", output)
        # Pipe-table ban on the whole output.
        self.assertNotIn("|---", output)
        self.assertNotIn("| # |", output)

    def test_format_report_was_only_for_genuine_specials(self):
        """REGRESSION (user report): "(was $x)" must appear ONLY for
        items the store marks on special with a WasPrice — never for the
        always-on team discount. Covers both WW and Coles lines."""
        from core.price_comparator import ComparisonReport, format_report
        from core.price_comparator import BasketItem

        ww_special = BasketItem(
            name="Bega Fetta Crumbled",
            prices={"woolworths": 3.00, "coles": 2.50},
            sources={"woolworths": "live", "coles": "live"},
            specials={
                "woolworths": "Was $4.00",
                "coles": "Was $2.90",
            },
            brand="Bega",
            is_woolworths_home_brand=False,
        )
        ww_regular = BasketItem(
            name="Regular Milk",
            prices={"woolworths": 4.00, "coles": 3.20},
            sources={"woolworths": "sheet", "coles": "sheet"},
            specials={},
            brand="A2",
            is_woolworths_home_brand=False,
        )
        report = ComparisonReport(
            items=[ww_special, ww_regular],
            raw_totals={"woolworths": 7.00, "coles": 5.70},
            store_coverage={"woolworths": 2, "coles": 2},
            team_discount_applied=True,
            team_discount_savings=0.35,
            final_totals={"woolworths": 6.65, "coles": 5.70},
            cheapest_store="coles",
            most_expensive_store="woolworths",
            max_savings=0.95,
            not_available={"woolworths": [], "coles": []},
        )
        output = format_report(report)
        # Genuine specials: discounted price + genuine store was-price.
        self.assertIn("(was $4.00)", output)   # WW special line
        self.assertIn("(was $2.90)", output)   # Coles special line
        # Regular item: discounted price only — no "was" at all.
        self.assertNotIn("was $3.80", output)  # 4.00 base-discounted
        # "(was $4.00)" appears exactly once — the genuine WW special.
        self.assertEqual(output.count("(was $4.00)"), 1)

    def test_compare_auto_mode_sheet_then_live(self):
        """auto mode: sheet items use sheet, missing items fall back to live."""
        from core.price_comparator import compare_basket
        from extractors.models import ProductItem

        header = _make_header()
        rows = [
            header,
            ["Milk", "Dairy", "2L", "$3.00", "$2.80", "",
             "", "", "milk", "", "", "", "", "", ""],
        ]
        ws = FakeWorksheet(rows)

        def stub_search(term, page_size=5):
            if "bread" in term.lower():
                return [ProductItem("woolworths", "White Bread", 2.50)]
            return []

        def stub_coles_status(term, page_size=5):
            return ([], "unavailable")

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_search,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=stub_coles_status,
        ):
            report = compare_basket(
                "milk, bread", mode="auto", worksheet=ws,
            )
        self.assertEqual(len(report.items), 2)
        # Milk: sheet
        self.assertIn(
            "sheet", report.items[0].sources.get("woolworths", "")
        )
        # Bread: live
        self.assertEqual(
            report.items[1].sources.get("woolworths", ""), "live"
        )

    # ========================================================================
    # Live search (noauth curl_cffi + Scrape.do) tests — Phase 9.7.c
    # ========================================================================

    def test_compare_auto_noauth_woolworths_live(self):
        """auto mode uses fetch_woolworths_search_noauth for live fallback."""
        from core.price_comparator import compare_basket
        from extractors.models import ProductItem

        header = _make_header()
        rows = [header]
        ws = FakeWorksheet(rows)

        def stub_noauth(term, page_size=5):
            return [ProductItem("woolworths", "Fresh Milk 2L", 3.50,
                                is_special=True, special_desc="Half Price")]

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_noauth,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=lambda t, **kw: ([], "unavailable"),
        ):
            report = compare_basket("milk", mode="auto", worksheet=ws)
        self.assertEqual(len(report.items), 1)
        self.assertEqual(report.items[0].sources["woolworths"], "live")
        self.assertEqual(report.items[0].prices["woolworths"], 3.50)

    def test_compare_auto_scrapedo_coles_live(self):
        """auto mode uses Scrape.do for Coles live search fallback."""
        from core.price_comparator import compare_basket
        from extractors.models import ProductItem

        header = _make_header()
        rows = [header]
        ws = FakeWorksheet(rows)

        def stub_coles(term, page_size=5):
            return ([ProductItem("coles", "Coles Bread 650g", 2.80)], "ok")

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=lambda t, **kw: [],
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=stub_coles,
        ):
            report = compare_basket("bread", mode="auto", worksheet=ws)
        self.assertEqual(len(report.items), 1)
        # IN-1 (spec §3.2.4): Woolworths empty -> the item renders as the
        # found-block with Coles' closest product, NO price at all.
        self.assertEqual(report.items[0].prices, {})
        self.assertEqual(report.items[0].uom_reason, "no_results_woolworths")
        self.assertEqual(
            report.items[0].closest.get("coles", {}).get("name"),
            "Coles Bread 650g",
        )

    def test_compare_auto_both_stores_live(self):
        """Both stores return live results, cheapest is computed."""
        from core.price_comparator import compare_basket
        from extractors.models import ProductItem

        header = _make_header()
        rows = [header]
        ws = FakeWorksheet(rows)

        def stub_ww(term, page_size=5):
            return [ProductItem("woolworths", "WW Milk 2L", 3.50,
                                size="2L")]

        def stub_coles(term, page_size=5):
            return ([ProductItem("coles", "Coles Milk 2L", 3.20,
                                 size="2L")], "ok")

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_ww,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=stub_coles,
        ):
            report = compare_basket("milk", mode="auto", worksheet=ws)
        self.assertEqual(len(report.items), 1)
        self.assertEqual(report.raw_totals["woolworths"], 3.50)
        self.assertEqual(report.raw_totals["coles"], 3.20)
        self.assertEqual(report.cheapest_store, "coles")

    def test_compare_auto_both_stores_empty_not_found(self):
        """Both stores return empty — item not found, flagged."""
        from core.price_comparator import compare_basket

        header = _make_header()
        rows = [header]
        ws = FakeWorksheet(rows)

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=lambda t, **kw: [],
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=lambda t, **kw: ([], "empty"),
        ):
            report = compare_basket("xyzunknown", mode="auto", worksheet=ws)
        # Item should be flagged as not available at both stores
        na = report.not_available
        self.assertIn("woolworths", na)
        self.assertIn("coles", na)

    def test_compare_auto_woolworths_exception_fallback(self):
        """Woolworths noauth raises -> caught, Coles still works."""
        from core.price_comparator import compare_basket
        from extractors.models import ProductItem

        header = _make_header()
        rows = [header]
        ws = FakeWorksheet(rows)

        def stub_ww_fail(term, page_size=5):
            raise RuntimeError("curl_cffi unavailable")

        def stub_coles(term, page_size=5):
            return ([ProductItem("coles", "Coles Milk 2L", 3.20)], "ok")

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_ww_fail,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=stub_coles,
        ):
            report = compare_basket("milk", mode="auto", worksheet=ws)
        # IN-1 (spec §3.2.4): Woolworths empty -> found-block, no price.
        # Coles still responded — its closest product is captured.
        self.assertNotIn("coles", report.raw_totals)
        self.assertEqual(report.items[0].prices, {})
        self.assertEqual(report.items[0].uom_reason, "no_results_woolworths")
        self.assertEqual(
            report.items[0].closest.get("coles", {}).get("name"),
            "Coles Milk 2L",
        )


class TestUomReportMatrix(unittest.TestCase):
    """Plan matrix P-1..P-14: identity/provenance lines, found-block,
    UOM gate scope (0.1), totals exclusion, and the no-per-unit rule."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ws(self, rows):
        """FakeWorksheet from raw rows (header first)."""
        return FakeWorksheet(rows)

    def _auto(self, names, ww, coles_result, ws, **kwargs):
        """compare_basket(mode=auto) with both store fns patched."""
        def stub_ww(term, page_size=5):
            return ww

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_ww,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search_status",
            side_effect=lambda t, **kw: coles_result,
        ):
            return compare_basket(names, mode="auto", worksheet=ws, **kwargs)

    def _live(self, names, ww, coles, **kwargs):
        """compare_basket(mode=live) with the legacy fns patched."""
        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search",
            side_effect=lambda t, **kw: ww,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search",
            side_effect=lambda t, **kw: coles,
        ):
            return compare_basket(names, mode="live", **kwargs)

    @staticmethod
    def _prod(store, name, price, size="", special_desc="", is_special=False,
              brand=""):
        """ProductItem fixture shorthand."""
        from extractors.models import ProductItem
        return ProductItem(store=store, raw_name=name, price=price,
                           size=size, special_desc=special_desc,
                           is_special=is_special, brand=brand)

    # ------------------------------------------------------------------
    # P-1..P-3: report rendering
    # ------------------------------------------------------------------
    def test_p1_live_store_line_identity_suffix(self):
        """P-1: store line renders ' — <name> <size> (live)'."""
        ws = self._ws([_make_header()])
        ww = [self._prod("woolworths", "Debco 25L Potting Mix", 19.50,
                         size="25L", brand="Debco")]
        coles = ([self._prod("coles", "Coles 30L Potting Mix", 8.40,
                             size="30L")], "ok")
        report = self._auto("potting mix", ww, coles, ws,
                            team_discount=False)
        text = format_report(report)
        self.assertIn("— Debco 25L Potting Mix 25L (live)", text)
        self.assertIn("— Coles 30L Potting Mix 30L (live)", text)

    def test_p2_sheet_store_line_provenance(self):
        """P-2: store line renders the '(sheet)' tag for sheet prices."""
        rows = [
            _make_header(),
            ["Oat Milk 1L", "Dairy", "1L", "$3.20", "$3.50", "", "Bega",
             "2026-08-28", "", "", "", "", "", "", ""],
        ]
        # Auto-mode sheet hit: lookup tags sources "sheet" and carries
        # the matched Col A / Col C identity for the suffix.
        report = self._auto("oat milk 1l", [], ([], "empty"), rows and
                            self._ws(rows), team_discount=False)
        self.assertEqual(report.items[0].sources.get("woolworths"), "sheet")
        text = format_report(report)
        self.assertIn("(sheet)", text)
        self.assertIn("$3.20 — Oat Milk 1L 1L (sheet)", text)

    def test_p3_found_block_exact_wording(self):
        """P-3: found-block prints the EXACT §3.3 wording."""
        ws = self._ws([_make_header()])
        ww = [self._prod("woolworths", "Aluminium Foil 10m", 2.00,
                         size="10m")]
        coles = ([self._prod("coles", "Aluminium Foil 150m", 9.50,
                             size="150m")], "ok")
        report = self._auto("aluminium foil", ww, coles, ws)
        text = format_report(report)
        self.assertIn("⚠️ No matching product — sizes don't compare.", text)
        self.assertIn("Woolworths: Aluminium Foil 10m", text)
        # Store labels padded to equal width (names share column 12).
        self.assertIn("Coles:      Aluminium Foil 150m", text)
        self.assertIn("💬 Reply 'expand' to see more results.", text)

    # ------------------------------------------------------------------
    # P-4..P-6: totals exclusion + unavailable line
    # ------------------------------------------------------------------
    def test_p4_non_comparable_excluded_from_totals(self):
        """P-4: non-comparable item contributes to NO totals."""
        rows = [
            _make_header(),
            ["Oat Milk 1L", "Dairy", "1L", "$3.20", "$3.50", "", "Bega",
             "2026-08-28", "", "", "", "", "", "", ""],
        ]
        ws = self._ws(rows)
        ww = [self._prod("woolworths", "Aluminium Foil 10m", 2.00,
                         size="10m")]
        coles = ([self._prod("coles", "Aluminium Foil 150m", 9.50,
                             size="150m")], "ok")
        report = self._auto("oat milk 1l, aluminium foil", ww, coles, ws,
                            team_discount=False)
        self.assertEqual(report.raw_totals.get("woolworths"), 3.20)
        self.assertEqual(report.raw_totals.get("coles"), 3.50)

    def test_p5_non_comparable_never_wins(self):
        """P-5: cheapest unchanged by a non-comparable item's presence."""
        rows = [
            _make_header(),
            ["Oat Milk 1L", "Dairy", "1L", "$3.20", "$3.00", "", "Bega",
             "2026-08-28", "", "", "", "", "", "", ""],
        ]
        ws = self._ws(rows)
        ww = [self._prod("woolworths", "Aluminium Foil 10m", 2.00,
                         size="10m")]
        coles = ([self._prod("coles", "Aluminium Foil 150m", 9.50,
                             size="150m")], "ok")
        report = self._auto("oat milk 1l, aluminium foil", ww, coles, ws,
                            team_discount=False)
        self.assertEqual(report.cheapest_store, "coles")
        self.assertEqual(report.max_savings, 0.20)

    def test_p6_unavailable_store_line(self):
        """P-6: WW-only shows the price + the Coles-unavailable line."""
        ws = self._ws([_make_header()])
        ww = [self._prod("woolworths", "WW Bread 650g", 2.50, size="650g")]
        report = self._auto("bread", ww, ([], "unavailable"), ws,
                            team_discount=False)
        self.assertEqual(report.items[0].prices.get("woolworths"), 2.50)
        text = format_report(report)
        self.assertIn("⚠️ Coles not checked (unavailable)", text)
        self.assertIn("$2.50", text)

    # ------------------------------------------------------------------
    # P-7..P-10: gate scope (interpretation 0.1)
    # ------------------------------------------------------------------
    def test_p7_sheet_vs_sheet_unchanged_golden(self):
        """P-7: sheet compare never gated — golden regression."""
        rows = [
            _make_header(),
            ["Soft Drink", "Drinks", "2L", "$4.00", "$3.00", "", "",
             "2026-08-28", "", "", "", "", "", "", ""],
            ["Juice", "Drinks", "600mL", "$2.00", "$5.00", "", "",
             "2026-08-28", "", "", "", "", "", "", ""],
        ]
        report = compare_basket("soft drink, juice", mode="sheet",
                                worksheet=self._ws(rows))
        # 2L-vs-600mL would NEVER pass the live gate — sheet prices
        # compare exactly as before regardless.
        self.assertEqual(report.raw_totals.get("woolworths"), 6.00)
        self.assertEqual(report.raw_totals.get("coles"), 8.00)
        self.assertEqual(report.cheapest_store, "woolworths")

    def test_p8_sheet_vs_live_mix_not_gated(self):
        """P-8: mixed basket — sheet item + live item both priced."""
        rows = [
            _make_header(),
            ["Soft Drink", "Drinks", "2L", "$4.00", "$3.00", "", "",
             "2026-08-28", "", "", "", "", "", "", ""],
        ]
        ws = self._ws(rows)
        ww = [self._prod("woolworths", "Debco 25L Potting Mix", 19.50,
                         size="25L")]
        coles = ([self._prod("coles", "Coles 30L Potting Mix", 8.40,
                             size="30L")], "ok")
        report = self._auto("soft drink, potting mix", ww, coles, ws,
                            team_discount=False)
        self.assertEqual(report.items[0].sources.get("woolworths"), "sheet")
        self.assertEqual(report.items[0].uom_reason, "")
        self.assertEqual(report.items[1].sources.get("woolworths"), "live")
        self.assertEqual(report.raw_totals.get("woolworths"), 23.50)

    def test_p9_both_live_gated_in_auto(self):
        """P-9: same items both live -> the gate applies (0.1)."""
        ws = self._ws([_make_header()])
        ww = [self._prod("woolworths", "Aluminium Foil 10m", 2.00,
                         size="10m")]
        coles = ([self._prod("coles", "Aluminium Foil 150m", 9.50,
                             size="150m")], "ok")
        report = self._auto("aluminium foil", ww, coles, ws)
        self.assertEqual(report.items[0].prices, {})
        self.assertEqual(report.items[0].uom_reason, "beyond_20pct")

    def test_p10_live_mode_routes_through_gate(self):
        """P-10: --mode live routes through the gate (IN-2)."""
        ww = [self._prod("woolworths", "Aluminium Foil 10m", 2.00,
                         size="10m")]
        coles = [self._prod("coles", "Aluminium Foil 150m", 9.50,
                            size="150m")]
        report = self._live("aluminium foil", ww, coles)
        self.assertEqual(report.items[0].prices, {})
        self.assertEqual(report.items[0].uom_reason, "beyond_20pct")
        self.assertEqual(report.raw_totals, {})

    # ------------------------------------------------------------------
    # P-11..P-14: rebuild guard, totals golden, fallback rendering
    # ------------------------------------------------------------------
    def test_p11_home_brand_rebuild_carries_new_fields(self):
        """P-11: step-3 rebuild keeps matched_names/sizes/closest."""
        ws = self._ws([_make_header()])
        ww = [self._prod("woolworths", "WW Home Brand Potting Mix 25L",
                         19.50, size="25L", brand="Woolworths")]
        coles = ([self._prod("coles", "Coles 30L Potting Mix", 8.40,
                             size="30L")], "ok")
        with patch(
            "core.woolworths_discounts.is_woolworths_home_brand",
            side_effect=lambda name, brand: True,
        ):
            report = self._auto("potting mix", ww, coles, ws)
        item = report.items[0]
        self.assertTrue(item.is_woolworths_home_brand)
        self.assertEqual(item.matched_names.get("woolworths"),
                         "WW Home Brand Potting Mix 25L")
        self.assertEqual(item.matched_sizes.get("coles"), "30L")

    def test_p12_totals_math_golden(self):
        """P-12: totals unchanged for a fully-comparable basket."""
        rows = [
            _make_header(),
            ["Oat Milk 1L", "Dairy", "1L", "$3.20", "$3.50", "", "Bega",
             "2026-08-28", "", "", "", "", "", "", ""],
            ["Tomato Paste 200g", "Pantry", "200g", "$1.80", "$1.50", "",
             "", "2026-08-28", "", "", "", "", "", "", ""],
        ]
        report = compare_basket("oat milk 1l, tomato paste 200g",
                                mode="sheet", worksheet=self._ws(rows),
                                team_discount=False)
        self.assertEqual(report.raw_totals,
                         {"woolworths": 5.00, "coles": 5.00})
        self.assertEqual(report.final_totals,
                         {"woolworths": 5.00, "coles": 5.00})
        # Perfect tie: a winner is still declared, savings zero.
        self.assertEqual(report.cheapest_store, "woolworths")
        self.assertEqual(report.max_savings, 0.0)

    def test_p13_no_prices_no_found_block(self):
        """P-13: empty closest + no prices -> existing rendering only."""
        ws = self._ws([_make_header()])
        report = self._auto("xyzunknown", [], ([], "empty"), ws)
        self.assertEqual(report.items[0].closest, {})
        text = format_report(report)
        self.assertIn("No prices available for any store", text)
        self.assertNotIn("No matching product", text)

    def test_p14_no_per_unit_price_strings(self):
        """P-14: report contains NO per-unit price strings, ever."""
        rows = [
            _make_header(),
            ["Oat Milk 1L", "Dairy", "1L", "$3.20", "$3.50", "", "Bega",
             "2026-08-28", "", "", "", "Was $4.00", "", "", ""],
        ]
        ws = self._ws(rows)
        ww = [self._prod("woolworths", "Aluminium Foil 10m", 2.00,
                         size="10m")]
        coles = ([self._prod("coles", "Aluminium Foil 150m", 9.50,
                             size="150m")], "ok")
        report = self._auto("oat milk 1l, aluminium foil", ww, coles, ws,
                            team_discount=False)
        text = format_report(report)
        for banned in ("/L", "/kg", "/100", "per 100", "per L", "per kg",
                       "per litre", "per kilo"):
            self.assertNotIn(banned, text)


class TestCompareAddReminder(unittest.TestCase):
    """D23 (WP1): the queue reminder in format_report — presence matrix."""

    REMINDER = "💬 Reply 'add item N' to queue a result for Wednesday."

    def _report(self, items):
        return ComparisonReport(items=items)

    def test_live_price_report_ends_with_reminder(self):
        item = BasketItem(
            name="milk",
            prices={"woolworths": 4.5, "coles": 4.2},
            sources={"woolworths": "live", "coles": "live"},
        )
        out = format_report(self._report([item]))
        self.assertTrue(out.rstrip().endswith(self.REMINDER))

    def test_found_block_only_report_ends_with_reminder(self):
        item = BasketItem(
            name="flour",
            closest={"woolworths": {"name": "WW Flour 2kg"}},
        )
        out = format_report(self._report([item]))
        self.assertTrue(out.rstrip().endswith(self.REMINDER))

    def test_sheet_only_report_has_no_reminder(self):
        item = BasketItem(
            name="milk",
            prices={"woolworths": 4.5, "coles": 4.2},
            sources={"woolworths": "sheet", "coles": "sheet"},
        )
        out = format_report(self._report([item]))
        self.assertNotIn(self.REMINDER, out)

    def test_mixed_report_reminder_appears_exactly_once(self):
        sheet_item = BasketItem(
            name="bread",
            prices={"woolworths": 3.0, "coles": 3.2},
            sources={"woolworths": "sheet", "coles": "sheet"},
        )
        live_item = BasketItem(
            name="milk",
            prices={"woolworths": 4.5},
            sources={"woolworths": "live"},
        )
        out = format_report(self._report([sheet_item, live_item]))
        self.assertEqual(out.count(self.REMINDER), 1)

    def test_empty_report_unchanged(self):
        out = format_report(ComparisonReport(items=[]))
        self.assertIn("No items provided.", out)
        self.assertNotIn(self.REMINDER, out)


class TestReportUnitSurfaces(unittest.TestCase):
    """A3/A4: title tag survives truncation; found-block shows size."""

    def test_found_block_shows_store_size_and_marker(self):
        from core.price_comparator import BasketItem, _found_block_lines
        item = BasketItem(
            name="flour", prices={}, sources={}, closest={
                "woolworths": {"name": "Flour Plain", "size": "1kg"},
                "coles": {"name": "Coles Flour", "size": ""},
            })
        lines = _found_block_lines(item)
        self.assertTrue(any(ln.endswith(" · 1kg") for ln in lines))
        self.assertTrue(
            any(" · ⚠️ unit unavailable" in ln for ln in lines))

    def test_format_report_title_tag_survives_truncation(self):
        from core.price_comparator import ComparisonReport, format_report
        item = BasketItem(
            name="Full Cream Milk Chocolate Organic Supreme",  # > 24 cells
            prices={"woolworths": 3.0, "coles": 3.5},
            sources={"woolworths": "sheet", "coles": "sheet"},
            matched_sizes={"woolworths": "200g"},
        )
        out = format_report(ComparisonReport(items=[item]))
        block_line = next(
            ln for ln in out.split("\n") if ln.startswith("1. "))
        self.assertTrue(block_line.endswith(" · 200g"))
        self.assertIn("…", block_line)  # name truncated, tag never cut

    def test_format_report_title_shows_marker_when_no_sizes(self):
        from core.price_comparator import ComparisonReport, format_report
        item = BasketItem(
            name="Milk",
            prices={"woolworths": 3.0, "coles": 3.5},
            sources={"woolworths": "sheet", "coles": "sheet"},
        )
        out = format_report(ComparisonReport(items=[item]))
        block_line = next(
            ln for ln in out.split("\n") if ln.startswith("1. "))
        self.assertTrue(block_line.endswith(" · ⚠️ unit unavailable"))


class TestIdentitySuffixAlwaysUnit(unittest.TestCase):
    """A2: the size segment is always present (Rule A)."""

    def _item(self, sizes, names=None):
        from core.price_comparator import BasketItem
        return BasketItem(
            name="milk",
            prices={"woolworths": 3.0, "coles": 3.5},
            sources={"woolworths": "sheet", "coles": "sheet"},
            # `names={}` must mean "no matched names" — an `or` default
            # would silently replace the empty dict (it is falsy).
            matched_names=names if names is not None else {
                "woolworths": "Milk 1L", "coles": "Milk 1L"},
            matched_sizes=sizes,
        )

    def test_size_present_when_known(self):
        from core.price_comparator import _identity_suffix
        suffix = _identity_suffix(self._item({"woolworths": "1L"}),
                                  "woolworths")
        self.assertEqual(suffix, " — Milk 1L 1L (sheet)")

    def test_marker_present_when_missing(self):
        from core.price_comparator import _identity_suffix
        suffix = _identity_suffix(self._item({}), "woolworths")
        self.assertEqual(suffix, " — Milk 1L unit unavailable (sheet)")

    def test_empty_when_no_matched_name(self):
        from core.price_comparator import _identity_suffix
        suffix = _identity_suffix(self._item({}, names={}), "woolworths")
        self.assertEqual(suffix, "")


if __name__ == "__main__":
    unittest.main()
