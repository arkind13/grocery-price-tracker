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

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_search,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search",
            side_effect=lambda t, **kw: [],
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
            "extractors.coles_extractor.fetch_coles_search",
            side_effect=lambda t, **kw: [],
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
            return [ProductItem("coles", "Coles Bread 650g", 2.80)]

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=lambda t, **kw: [],
        ), patch(
            "extractors.coles_extractor.fetch_coles_search",
            side_effect=stub_coles,
        ):
            report = compare_basket("bread", mode="auto", worksheet=ws)
        self.assertEqual(len(report.items), 1)
        self.assertEqual(report.items[0].sources["coles"], "live")
        self.assertEqual(report.items[0].prices["coles"], 2.80)

    def test_compare_auto_both_stores_live(self):
        """Both stores return live results, cheapest is computed."""
        from core.price_comparator import compare_basket
        from extractors.models import ProductItem

        header = _make_header()
        rows = [header]
        ws = FakeWorksheet(rows)

        def stub_ww(term, page_size=5):
            return [ProductItem("woolworths", "WW Milk 2L", 3.50)]

        def stub_coles(term, page_size=5):
            return [ProductItem("coles", "Coles Milk 2L", 3.20)]

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_ww,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search",
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
            "extractors.coles_extractor.fetch_coles_search",
            side_effect=lambda t, **kw: [],
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
            return [ProductItem("coles", "Coles Milk 2L", 3.20)]

        with patch(
            "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
            side_effect=stub_ww_fail,
        ), patch(
            "extractors.coles_extractor.fetch_coles_search",
            side_effect=stub_coles,
        ):
            report = compare_basket("milk", mode="auto", worksheet=ws)
        # Coles should still have a result
        self.assertIn("coles", report.raw_totals)
        self.assertEqual(report.raw_totals["coles"], 3.20)


if __name__ == "__main__":
    unittest.main()
