#!/usr/bin/env python3
"""Tests for core.telegram_format (Telegram Style Kit).

Covers the mandatory test matrix (implementation-plan §5.1) plus the
real-formatter invariant tests (§5.3): no pipe tables ever, and the
fenced TOTALS block lines are all equal length.
"""
from datetime import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import telegram_format as tf


def _strip_fences(block: str) -> list[str]:
    """Return the content lines of a fenced block (between the fences)."""
    lines = block.split("\n")
    assert lines[0] == "```" and lines[-1] == "```"
    return lines[1:-1]


class TestHeaderAndDividers(unittest.TestCase):
    """Skeleton pieces: header, subheader, divider."""

    def test_header_caps_and_divider(self):
        """Icon + UPPERCASED title + heavy divider second line."""
        out = tf.header("Basket Comparison", "🛒")
        lines = out.split("\n")
        self.assertEqual(lines[0], "🛒 BASKET COMPARISON")
        self.assertEqual(lines[1], "━" * 20)

    def test_subheader_light_divider(self):
        """Light `─` x10 line first; icon optional on the label line."""
        with_icon = tf.subheader("HOME BRAND EXTRA", "🏷️")
        lines = with_icon.split("\n")
        self.assertEqual(lines[0], "─" * 10)
        self.assertEqual(lines[1], "🏷️ HOME BRAND EXTRA")

        without_icon = tf.subheader("TOTALS")
        self.assertEqual(without_icon.split("\n")[0], "─" * 10)
        self.assertIn("TOTALS", without_icon)

    def test_divider_default_and_custom(self):
        """divider() defaults to light x10 and accepts char/width."""
        self.assertEqual(tf.divider(), "─" * 10)
        self.assertEqual(tf.divider("=", 4), "====")


class TestFencedTable(unittest.TestCase):
    """fenced_table: alignment, budget, truncation, borders, edges."""

    def test_fenced_table_all_rows_equal_width(self):
        """Strip fences -> every content line has identical len()."""
        out = tf.fenced_table(
            ["Store", "Raw", "Final"],
            [
                ["Woolworths", "$23.40", "$21.75"],
                ["Coles", "$24.10", "$24.10"],
            ],
            box=True,
        )
        lines = _strip_fences(out)
        self.assertEqual(len({len(line) for line in lines}), 1)

        plain = tf.fenced_table(
            ["A", "B"], [["one", "two"], ["three", "four"]]
        )
        plain_lines = _strip_fences(plain)
        self.assertEqual(len({len(l) for l in plain_lines}), 1)

    def test_fenced_table_respects_width_budget(self):
        """Max visible width <= MAX_BLOCK_WIDTH with long cells."""
        out = tf.fenced_table(
            ["Product", "Price"],
            [
                ["A very long product name that surely exceeds budget", "$12.34"],
                ["Short", "$1.00"],
            ],
        )
        for line in _strip_fences(out):
            self.assertLessEqual(tf._cells(line), tf.MAX_BLOCK_WIDTH)

    def test_fenced_table_truncates_with_ellipsis(self):
        """Over-wide cells end in ... and never exceed the budget."""
        long_name = "Extraordinary Supermarket Product Name 900g"
        out = tf.fenced_table(
            ["Product", "Price"], [[long_name, "$9.99"]]
        )
        lines = _strip_fences(out)
        self.assertTrue(any(tf.ELLIPSIS in line for line in lines))
        for line in lines:
            self.assertLessEqual(tf._cells(line), tf.MAX_BLOCK_WIDTH)

    def test_fenced_table_box_borders(self):
        """box=True draws top/bottom borders and equal-length lines."""
        out = tf.fenced_table(
            ["Store", "Raw"],
            [["Woolworths", "$23.40"], ["Coles", "$24.10"]],
            box=True,
        )
        lines = _strip_fences(out)
        self.assertTrue(lines[0].startswith("╔═") and lines[0].endswith("╗"))
        self.assertTrue(lines[-1].startswith("╚═") and lines[-1].endswith("╝"))
        for line in lines[1:-1]:
            self.assertTrue(line.startswith("║") and line.endswith("║"))
        self.assertEqual(len({len(line) for line in lines}), 1)

    def test_fenced_table_empty_rows(self):
        """Headers-only renders when rows is empty; [] headers raises."""
        out = tf.fenced_table(["A", "B"], [])
        lines = _strip_fences(out)
        self.assertEqual(len(lines), 1)
        self.assertIn("A", lines[0])
        self.assertIn("B", lines[0])

        with self.assertRaises(ValueError):
            tf.fenced_table([], [["x"]])

    def test_fenced_table_money_columns_right_aligned(self):
        """Money-shaped columns are right aligned (pad on the left)."""
        out = tf.fenced_table(
            ["Item", "Cost"], [["Milk", "$1.00"], ["Bread roll", "$2.50"]]
        )
        lines = _strip_fences(out)
        header, row1, row2 = lines[0], lines[1], lines[2]
        # All money cells end at the same offset (right-aligned column).
        self.assertEqual(header.rstrip().endswith("Cost"), True)
        self.assertTrue(row1.rstrip().endswith("$1.00"))
        self.assertTrue(row2.rstrip().endswith("$2.50"))
        self.assertEqual(len(row1), len(row2))


class TestMoneyAndScalars(unittest.TestCase):
    """money(), kv(), warn/ok/fail, truncate()."""

    def test_money_formats(self):
        """0/None/positive/negative render per spec §5.1."""
        self.assertEqual(tf.money(0), "$0.00")
        self.assertEqual(tf.money(None), "—")
        self.assertEqual(tf.money(4), "$4.00")
        self.assertEqual(tf.money(-1.5), "−$1.50")

    def test_truncate_short_unchanged(self):
        """Strings within budget pass through untouched."""
        self.assertEqual(tf.truncate("short", 10), "short")
        self.assertEqual(tf.truncate("0123456789", 10), "0123456789")
        self.assertEqual(tf.truncate("", 10), "")

    def test_truncate_long_ellipsized(self):
        """Long strings get an ellipsis; len never exceeds width."""
        out = tf.truncate("a" * 40, 10)
        self.assertLessEqual(len(out), 10)
        self.assertTrue(out.endswith("…"))

        # Emoji count as 2 cells: budget must still hold.
        out2 = tf.truncate("🟢" * 20, 10)
        self.assertLessEqual(tf._cells(out2), 10)


class TestStoreAndItemBlocks(unittest.TestCase):
    """store_line() and item_block()."""

    def test_store_line_alignment(self):
        """Woolworths/Coles lines: price starts at the same cell offset."""
        ww = tf.store_line("woolworths", "$2.47")
        coles = tf.store_line("coles", "$3.50")
        self.assertEqual(ww.index("$"), coles.index("$"))
        self.assertEqual(
            tf._cells(ww[: ww.index("$")]),
            tf._cells(coles[: coles.index("$")]),
        )
        # Icons + canonical labels present.
        self.assertTrue(ww.startswith("🟢 Woolworths"))
        self.assertTrue(coles.startswith("🔴 Coles"))

    def test_store_line_was_price(self):
        """(was $x) suffix appended when `was` given."""
        out = tf.store_line("coles", "$3.50", was="$2.90")
        self.assertTrue(out.endswith("(was $2.90)"))
        self.assertNotIn("(was", tf.store_line("coles", "$3.50"))

    def test_store_line_unknown_store(self):
        """Unknown stores: no icon, label as given."""
        out = tf.store_line("Aldi", "$1.99")
        self.assertNotIn("🟢", out)
        self.assertNotIn("🔴", out)
        self.assertIn("Aldi", out)
        self.assertIn("$1.99", out)

    def test_item_block_home_brand_marker(self):
        """🏠 appended when home_brand=True; name truncated at budget."""
        prices = [tf.store_line("woolworths", "$3.32")]
        out = tf.item_block(2, "Full Cream Milk 2L", prices, home_brand=True)
        lines = out.split("\n")
        self.assertTrue(lines[0].startswith("2. Full Cream Milk 2L"))
        self.assertIn("🏠", lines[0])
        self.assertEqual(lines[1], "   " + prices[0])

        long_name = "An Extremely Long Product Name That Will Not Fit"
        out2 = tf.item_block(1, long_name, [])
        first = out2.split("\n")[0]
        # "N. " prefix + name cells <= MAX_NAME_WIDTH.
        self.assertLessEqual(tf._cells(first) - 3, tf.MAX_NAME_WIDTH)
        self.assertIn("…", first)

    def test_item_block_numbered_lines_indented(self):
        """Store lines carry a uniform 3-space indent."""
        out = tf.item_block(
            1, "Milk", ["🟢 Woolworths  $1.00", "🔴 Coles       $2.00"]
        )
        for line in out.split("\n")[1:]:
            self.assertTrue(line.startswith("   "))


class TestStatusLines(unittest.TestCase):
    """kv(), warn/ok/fail, tail(), footer()."""

    def test_kv_separator(self):
        """Exactly one `·` between label and value."""
        out = tf.kv("label", "value")
        self.assertEqual(out, "label · value")
        self.assertEqual(out.count("·"), 1)

    def test_warn_ok_fail_icons(self):
        """⚠️ / ✅ / ❌ prefixes."""
        self.assertEqual(tf.warn("low stock"), "⚠️ low stock")
        self.assertEqual(tf.ok("written"), "✅ written")
        self.assertEqual(tf.fail("not found"), "❌ not found")

    def test_tail_line(self):
        """🏆 + winner + savings; (vs X) appended when `vs` given."""
        out = tf.tail("Woolworths", 2.35)
        self.assertEqual(out, "🏆 Cheapest: Woolworths — you save $2.35")
        out_vs = tf.tail("Woolworths", 2.35, vs="Coles")
        self.assertTrue(out_vs.endswith("(vs Coles)"))

    def test_footer_timestamp(self):
        """⏱️ prefix; deterministic when ts is passed."""
        out = tf.footer(datetime(2026, 8, 28, 14, 5))
        self.assertEqual(out, "⏱️ 2026-08-28 14:05")
        self.assertTrue(tf.footer().startswith("⏱️ "))


class TestNoPipeTablesEver(unittest.TestCase):
    """Composite message from every function stays pipe-free (§5.1 #17)."""

    def test_no_pipe_tables_ever(self):
        """'|---' and '| # |' never appear in a full composite message."""
        parts = [
            tf.header("Basket Comparison", "🛒"),
            tf.subheader("HOME BRAND EXTRA", "🏷️"),
            tf.divider(),
            tf.item_block(
                1,
                "Full Cream Milk 2L",
                [
                    tf.store_line("woolworths", "$3.32", was="$3.68"),
                    tf.store_line("coles", "$3.40"),
                ],
                home_brand=True,
            ),
            tf.fenced_table(
                ["Store", "Raw", "Final"],
                [["Woolworths", "$23.40", "$21.75"]],
                box=True,
            ),
            tf.kv("Items", "2"),
            tf.money(2.35),
            tf.warn("1 item missing at Coles"),
            tf.ok("sheet synced"),
            tf.fail("no prices"),
            tf.tail("Woolworths", 2.35, vs="Coles"),
            tf.truncate("Some long name here", 10),
            tf.footer(datetime(2026, 8, 28, 14, 5)),
        ]
        composite = "\n".join(parts)
        self.assertNotIn("|---", composite)
        self.assertNotIn("| # |", composite)


# ============================================================================
# §5.3 invariant tests — the REAL formatters stay pipe-free
# ============================================================================


def _fixture_report():
    """Build a small ComparisonReport matching the §5.2 fixture shape."""
    from core.price_comparator import BasketItem, ComparisonReport

    item = BasketItem(
        name="Woolworths Milk",
        prices={"woolworths": 4.00, "coles": 3.20},
        sources={"woolworths": "sheet", "coles": "sheet"},
        brand="Woolworths",
        is_woolworths_home_brand=True,
    )
    return ComparisonReport(
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
        warnings=["Monthly discount already used this month"],
        not_available={"woolworths": [], "coles": []},
    )


class TestRealFormatterInvariants(unittest.TestCase):
    """format_report / format_specials_report / format_discount_report
    never emit pipe tables; the compare TOTALS box is equal-width."""

    def test_format_report_pipe_free_and_box_aligned(self):
        """No pipes; the fenced TOTALS block lines are equal length."""
        from core.price_comparator import format_report

        output = format_report(_fixture_report())
        self.assertNotIn("|---", output)
        self.assertNotIn("| # |", output)

        lines = output.split("\n")
        starts = [i for i, ln in enumerate(lines) if ln.strip() == "```"]
        self.assertGreaterEqual(len(starts), 2)
        block = lines[starts[0] + 1 : starts[1]]
        self.assertEqual(len({len(ln) for ln in block}), 1)

    def test_format_specials_report_pipe_free(self):
        """specials report contains no pipe-table markup."""
        from core.specials_reporter import format_specials_report

        specials = [
            {"name": "Coke 24-pack", "store": "coles",
             "special_desc": "was $24.50", "price": 19.00, "brand": ""},
            {"name": "Milk 2L", "store": "woolworths",
             "special_desc": "Half Price", "price": 3.00,
             "brand": "Bega"},
        ]
        output = format_specials_report(specials, "woolworths")
        self.assertNotIn("|---", output)
        self.assertNotIn("| # |", output)
        self.assertIn("2.85", output)     # 3.00 base-discounted
        self.assertNotIn("was $2.85", output)  # no team-discount "was"
        self.assertIn("was $24.50", output)    # genuine Coles desc intact

    def test_format_discount_report_pipe_free(self):
        """discount report contains no pipe-table markup."""
        from core.woolworths_discounts import format_discount_report

        items = [
            {"name": "WW Milk", "brand": "Woolworths",
             "original_price": 4.00, "base_price": 3.80,
             "discounted_price": 3.61, "applied": True,
             "home_extra_applied": True},
        ]
        output = format_discount_report(
            items, 0.45, 0.0, 0.0,
            home_extra_total=0.19, home_brand_count=1,
        )
        self.assertNotIn("|---", output)
        self.assertNotIn("| # |", output)
        self.assertIn("3.61", output)


if __name__ == "__main__":
    unittest.main()
