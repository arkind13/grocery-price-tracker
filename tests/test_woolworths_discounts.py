#!/usr/bin/env python3
"""Unit tests for the always-on Woolworths display discounts engine.

Covers: home-brand detection (32 canonical labels + macro alias),
compounding discount math (5% base + 5% home extra), formatting helpers,
apply_woolworths_discounts() (base on ALL WW items, extra on home brands),
and a regression guard for the monthly tracker (Section E unchanged).

No network, no live sheet.
"""
from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))


# Canonical 32-entry home-brand list, human-display spellings
# (spec architecture-spec.md §3). Normalization is under test.
CANONICAL_HOME_BRANDS = [
    "Apollo", "Balnea", "Baxters", "Bell Farms", "Clean", "Essentials",
    "Farmer's Own", "Help at Hand", "Hillview", "Inspire", "La Gina",
    "La Meida", "La Mesita", "Lantern Alley", "Little Ones",
    "Little Wishes", "Lolly Go Round", "Macro Wholefoods Market",
    "Market Value", "Plantitude", "Ready Chef", "Smiling Tums", "Smitten",
    "Strength Meals Co", "Strike", "Sushi Izu", "The Odd Bunch",
    "Thomas Dux", "Voeu", "Woolworths BBQ", "Woolworths Cook",
    "Woolworths",
]


class TestHomeBrandDetection(unittest.TestCase):
    """Detection rules (spec §4): exact brand match / Home marker /
    woolworths prefix / macro alias; name fallback only when brand empty."""

    def test_all_32_brand_labels_match(self):
        """All 32 canonical labels match via the brand field (exact eq)."""
        from core.woolworths_discounts import is_woolworths_home_brand
        for label in CANONICAL_HOME_BRANDS:
            with self.subTest(label=label):
                self.assertTrue(
                    is_woolworths_home_brand("anything", label),
                    f"brand {label!r} should be a home brand",
                )

    def test_home_marker_matches(self):
        """The literal sheet marker 'Home' (any case) matches."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertTrue(is_woolworths_home_brand("Milk", "Home"))
        self.assertTrue(is_woolworths_home_brand("Milk", "home"))
        self.assertTrue(is_woolworths_home_brand("Milk", "HOME"))

    def test_woolworths_prefix_variants(self):
        """Any brand starting with 'woolworths' matches (prefix rule)."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertTrue(is_woolworths_home_brand("", "Woolworths"))
        self.assertTrue(is_woolworths_home_brand("", "woolworths bbq"))
        self.assertTrue(is_woolworths_home_brand("", "WOOLWORTHS COOK"))
        # Prefix covers even unlisted suffixes.
        self.assertTrue(is_woolworths_home_brand("", "Woolworths Select"))

    def test_macro_short_alias(self):
        """'Macro' is the short-form alias for Macro Wholefoods Market."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertTrue(is_woolworths_home_brand("", "Macro"))
        self.assertTrue(is_woolworths_home_brand("", "MACRO"))

    def test_normalization_apostrophe_whitespace(self):
        """Apostrophes/punctuation stripped; whitespace collapsed."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertTrue(is_woolworths_home_brand("", "  Farmer's   OWN "))
        self.assertTrue(is_woolworths_home_brand(
            "", "macro wholefoods  market"
        ))

    def test_name_fallback_leading_label(self):
        """Empty brand: leading word-boundary label match wins."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertTrue(is_woolworths_home_brand("Macro Rolled Oats 1kg", ""))
        self.assertTrue(is_woolworths_home_brand("The Odd Bunch Apples", ""))

    def test_name_fallback_word_boundary(self):
        """Name fallback needs whole-word leading label, not substring."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertTrue(is_woolworths_home_brand("Essentials", ""))
        self.assertFalse(is_woolworths_home_brand("EssentialsAnything", ""))
        self.assertFalse(is_woolworths_home_brand("Coles Milk", ""))

    # -- negatives -------------------------------------------------------

    def test_golden_circle_is_not_home_brand(self):
        """'gold' label was dropped — Golden Circle must NOT match."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertFalse(
            is_woolworths_home_brand("Golden Circle Pineapple",
                                     "Golden Circle")
        )
        self.assertFalse(is_woolworths_home_brand("Golden Circle Juice", ""))

    def test_mr_clean_not_home_brand(self):
        """'Mr Clean' is not the 'clean' home brand (exact equality)."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertFalse(
            is_woolworths_home_brand("Mr Clean Magic Eraser", "Mr Clean")
        )

    def test_mid_name_occurrence_no_match(self):
        """Name fallback is leading-position only."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertFalse(is_woolworths_home_brand("Juice Gold Blend", ""))
        self.assertFalse(
            is_woolworths_home_brand("Dairy Farmers Bell Farms Yogurt", "")
        )

    def test_coles_and_third_party_brands(self):
        """Third-party brands never match via brand field."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertFalse(is_woolworths_home_brand("Milk", "Coles"))
        self.assertFalse(is_woolworths_home_brand("Cheese", "Bega"))
        self.assertFalse(is_woolworths_home_brand("Oat Milk", "Oatly"))

    def test_empty_inputs(self):
        """Both inputs empty -> False."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertFalse(is_woolworths_home_brand("", ""))
        self.assertFalse(is_woolworths_home_brand(None, None))

    def test_brand_field_beats_name(self):
        """Non-empty non-matching brand disables the name fallback."""
        from core.woolworths_discounts import is_woolworths_home_brand
        self.assertFalse(is_woolworths_home_brand("Woolworths Milk", "Bega"))


class TestDiscountMath(unittest.TestCase):
    """Compounding math per spec §5: round-per-item, then sum."""

    def test_regular_item_base_5pct(self):
        """Non-home item: single 5% cut."""
        from core.woolworths_discounts import discounted_woolworths_price
        res = discounted_woolworths_price(5.00, False)
        self.assertEqual(res["original"], 5.00)
        self.assertAlmostEqual(res["final"], 4.75)
        self.assertAlmostEqual(res["savings"], 0.25)
        self.assertFalse(res["is_home"])

    def test_home_brand_compounding(self):
        """Home item: 0.95 then 0.95 again -> $5.00 becomes $4.51.

        Locked to spec §5's compounding formula ($4.51), NOT the flat-10%
        $4.50 illustration that spec §10 shows erroneously.
        """
        from core.woolworths_discounts import discounted_woolworths_price
        res = discounted_woolworths_price(5.00, True)
        self.assertAlmostEqual(res["final"], 4.51)
        self.assertAlmostEqual(res["savings"], 0.49)
        self.assertTrue(res["is_home"])

    def test_home_brand_safe_value(self):
        """$8.00 home -> 7.60 -> 7.22."""
        from core.woolworths_discounts import discounted_woolworths_price
        res = discounted_woolworths_price(8.00, True)
        self.assertAlmostEqual(res["final"], 7.22)

    def test_round_per_item_then_sum(self):
        """Totals sum the rounded per-item finals (never round-of-sum)."""
        from core.woolworths_discounts import discounted_woolworths_price
        finals = [
            discounted_woolworths_price(5.00, True)["final"],   # 4.51
            discounted_woolworths_price(8.00, True)["final"],   # 7.22
            discounted_woolworths_price(4.00, False)["final"],  # 3.80
        ]
        self.assertAlmostEqual(sum(finals), 15.53)

    def test_format_discounted_price_plain_no_was(self):
        """Formatted string shows ONLY the discounted price — no team
        discount "(was $x)" suffix (reserved for genuine specials)."""
        from core.woolworths_discounts import format_discounted_price
        home = format_discounted_price(5.00, True)
        self.assertEqual(home, "$4.51")
        regular = format_discounted_price(4.00, False)
        self.assertEqual(regular, "$3.80")

    def test_was_price_from_special_desc(self):
        """Genuine "Was $X" specials text yields the was-price; free-text
        descs and empty input yield None."""
        from core.woolworths_discounts import was_price_from_special_desc
        self.assertEqual(was_price_from_special_desc("Was $4.50"), 4.50)
        self.assertEqual(was_price_from_special_desc("was $24.50"), 24.50)
        self.assertEqual(was_price_from_special_desc("WAS $3.00"), 3.00)
        self.assertIsNone(was_price_from_special_desc("Half Price"))
        self.assertIsNone(was_price_from_special_desc("2 for $4.50"))
        self.assertIsNone(was_price_from_special_desc(""))
        self.assertIsNone(was_price_from_special_desc(None))


class TestApplyWoolworthsDiscounts(unittest.TestCase):
    """Engine contract: base 5% on ALL WW items, extra 5% on home brands."""

    def test_base_applies_to_all_ww_items(self):
        """Mixed basket: every WW item discounted >=5%; extra only for home."""
        from core.woolworths_discounts import apply_woolworths_discounts

        items = [
            {"name": "Bega Cheese", "brand": "Bega", "price": 5.00},
            {"name": "WW Milk", "brand": "Woolworths", "price": 4.00},
            {"name": "Macro Rice", "brand": "", "price": 12.00},
        ]
        results = apply_woolworths_discounts(items, store="woolworths")
        self.assertEqual(len(results), 3)

        bega, ww_milk, macro_rice = results
        # Every item gets the base discount...
        self.assertTrue(all(r["applied"] for r in results))
        # Regular item: base only.
        self.assertAlmostEqual(bega["discounted_price"], 4.75)
        self.assertFalse(bega["home_extra_applied"])
        # Home by brand: compounded.
        self.assertAlmostEqual(ww_milk["discounted_price"], 3.61)
        self.assertTrue(ww_milk["home_extra_applied"])
        self.assertTrue(ww_milk["is_home"])
        # Home by name fallback (empty brand field).
        self.assertAlmostEqual(macro_rice["discounted_price"], 10.83)
        self.assertTrue(macro_rice["home_extra_applied"])
        self.assertTrue(macro_rice["is_home"])
        # Base savings = sum of (original - round(original*0.95, 2)).
        base_savings = sum(
            r["original_price"] - r["discounted_price"]
            for r in results if not r["home_extra_applied"]
        ) + sum(
            r["original_price"] - r["base_price"]
            for r in results if r["home_extra_applied"]
        )
        self.assertAlmostEqual(base_savings, 1.05)  # 0.25+0.20+0.60

    def test_non_woolworths_store_noop(self):
        """store='coles': prices unchanged, every flag False."""
        from core.woolworths_discounts import apply_woolworths_discounts

        items = [
            {"name": "Woolworths Milk", "brand": "Woolworths",
             "price": 3.00},
        ]
        results = apply_woolworths_discounts(items, store="coles")
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertAlmostEqual(r["discounted_price"], 3.00)
        self.assertFalse(r["applied"])
        self.assertFalse(r["home_extra_applied"])

    def test_object_and_dict_inputs(self):
        """Duck-typed ProductItem-style objects AND dicts both accepted."""
        from core.woolworths_discounts import apply_woolworths_discounts

        as_dict = {"name": "Odd Bunch Apples", "brand": "The Odd Bunch",
                   "price": 5.00}
        as_obj = SimpleNamespace(raw_name="Bega Cheese", brand="Bega",
                                 price=10.00)
        results = apply_woolworths_discounts([as_dict, as_obj],
                                             store="woolworths")
        self.assertAlmostEqual(results[0]["discounted_price"], 4.51)
        self.assertTrue(results[0]["home_extra_applied"])
        self.assertAlmostEqual(results[1]["discounted_price"], 9.50)
        self.assertFalse(results[1]["home_extra_applied"])


class TestMonthlyTrackerRegressionGuard(unittest.TestCase):
    """Section E (monthly usage tracker) must keep behaving identically."""

    def test_monthly_tracker_unchanged(self):
        """can_use -> mark_used -> blocked within same month."""
        from core.woolworths_discounts import (
            can_use_monthly_discount,
            mark_monthly_discount_used,
            monthly_discount_summary,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tracker_path = (
                Path(tmpdir) / "woolworths_discount_usage.json"
            )
            with patch(
                "core.woolworths_discounts.TRACKER_PATH", tracker_path
            ):
                self.assertTrue(can_use_monthly_discount())
                mark_monthly_discount_used()
                self.assertFalse(can_use_monthly_discount())
                summary = monthly_discount_summary()
                self.assertFalse(summary["available"])
                self.assertEqual(summary["history_len"], 1)


class TestFormatDiscountReport(unittest.TestCase):
    """Telegram-style discount sub-block (standalone + compact)."""

    def test_report_shows_base_and_home_extra_lines(self):
        """Standalone: base summary line total + home was->now lines."""
        from core.woolworths_discounts import format_discount_report

        items = [
            {"name": "WW Milk", "brand": "Woolworths",
             "original_price": 4.00, "base_price": 3.80,
             "discounted_price": 3.61, "applied": True,
             "home_extra_applied": True},
            {"name": "Bega Cheese", "brand": "Bega",
             "original_price": 5.00, "base_price": 4.75,
             "discounted_price": 4.75, "applied": True,
             "home_extra_applied": False},
        ]
        report = format_discount_report(
            items,
            team_discount_total=0.45,
            extra_discount_pct=0.0,
            extra_discount_savings=0.0,
            home_extra_total=0.19,
            home_brand_count=1,
        )
        self.assertIn("0.45", report)   # base summary line over ALL items
        self.assertIn("HOME BRAND EXTRA", report)
        self.assertIn("$3.80 \u2192 $3.61", report)  # was -> now line
        self.assertIn("0.19", report)   # home-extra total
        # Base 5% has NO per-item lines anymore (compaction).
        self.assertNotIn("Bega Cheese", report)
        # Pipe-table ban.
        self.assertNotIn("|---", report)
        self.assertNotIn("| # |", report)

    def test_compact_mode_drops_base_summary(self):
        """compact=True (embedded): base line omitted, home block kept."""
        from core.woolworths_discounts import format_discount_report

        items = [
            {"name": "WW Milk", "brand": "Woolworths",
             "original_price": 4.00, "base_price": 3.80,
             "discounted_price": 3.61, "applied": True,
             "home_extra_applied": True},
        ]
        report = format_discount_report(
            items, 0.20, 0.0, 0.0,
            home_extra_total=0.19, home_brand_count=1, compact=True,
        )
        self.assertNotIn("5% off all WW items", report)
        self.assertIn("HOME BRAND EXTRA", report)
        self.assertIn("0.19", report)

    def test_compact_nothing_applied_returns_empty(self):
        """compact=True with nothing applicable renders an empty string
        so the embedding report can skip the block entirely."""
        from core.woolworths_discounts import format_discount_report

        self.assertEqual(format_discount_report([], 0.5, 0.0, 0.0,
                                                compact=True), "")

    def test_standalone_nothing_applied_message(self):
        """Standalone no-op still reports 'No discounts applied.'."""
        from core.woolworths_discounts import format_discount_report

        self.assertEqual(
            format_discount_report([], 0.0, 0.0, 0.0),
            "No discounts applied.",
        )

    def test_backward_compatible_signature(self):
        """Old 4-positional-arg call sites still work."""
        from core.woolworths_discounts import format_discount_report

        report = format_discount_report([], 0.0, 10.0, 2.50)
        self.assertIn("Extra 10%", report)
        self.assertIn("2.50", report)


if __name__ == "__main__":
    unittest.main()
