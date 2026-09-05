#!/usr/bin/env python3
"""Unit tests for core/preferences (spec §6/§8 + plan §S5-S7).

No network, no sheet — FakeWorksheet simulates gspread; pending file
is patched into a temp dir.
Usage:
    python -m pytest tests/test_preferences.py -q
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

# Bootstrap sys.path so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent  # tests/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

import core.preferences as prefs
from core.preferences import (
    detect_multi_p,
    find_by_code,
    get_preferred,
    is_stale,
    list_subcategory_options,
    load_pending,
    read_qrs,
    render_disambiguation_prompt,
    render_override_warning,
    save_pending,
)


def _header_a_to_s():
    """Products_Master header A..S with the Q/R/S names."""
    header = [c for c in "ABCDEFGHIJKLMNOP"]
    header += ["Sub_Category", "Item_Code", "Preferred"]
    return header


class FakeWorksheet:
    """Mock gspread Worksheet (same pattern as tests/test_cli.py)."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]
        self.updates = []  # list of (values, range_name)

    def get_all_values(self):
        return [list(r) for r in self._values]

    def update(self, *, values, range_name):
        self.updates.append((values, range_name))
        import re
        m = re.match(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$", range_name)
        col = ord(m.group(1)) - ord("A")
        row = int(m.group(2)) - 1
        end_col = ord(m.group(3)) - ord("A") if m.group(3) else col
        width = end_col - col + 1
        for offset, vals in enumerate(values):
            r = row + offset
            while len(self._values) <= r:
                self._values.append([])
            self._values[r][col:col + width] = list(vals)


class TestReadQrs(unittest.TestCase):
    """read_qrs: header-driven Q/R/S parsing."""

    def test_read_qrs_parses_all_three_columns(self):
        ws = FakeWorksheet([
            _header_a_to_s(),
            ["Milk", *[""] * 15, "dairy", "ABC", "P"],
            ["Bread", *[""] * 15, "Bakery", "def", ""],
            ["Eggs", *[""] * 15, "", "", ""],
        ])
        rows = read_qrs(ws)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["subcategory"], "dairy")
        self.assertEqual(rows[0]["item_code"], "ABC")
        self.assertEqual(rows[0]["preferred"], "P")
        self.assertEqual(rows[1]["item_code"], "DEF")
        self.assertEqual(rows[2]["subcategory"], "")

    def test_read_qrs_missing_headers_yield_empty_fields(self):
        ws = FakeWorksheet([
            [c for c in "ABCDEFGHIJKLMNOP"],  # no Q/R/S headers
            ["Milk", *[""] * 15],
        ])
        rows = read_qrs(ws)
        self.assertEqual(rows[0]["subcategory"], "")
        self.assertEqual(rows[0]["item_code"], "")
        self.assertEqual(rows[0]["preferred"], "")

    def test_read_qrs_skips_empty_names(self):
        ws = FakeWorksheet([
            _header_a_to_s(),
            ["Milk", *[""] * 15, "dairy", "ABC", ""],
            ["", *[""] * 15, "ghost", "ZZZ", "P"],
        ])
        rows = read_qrs(ws)
        self.assertEqual([r["name"] for r in rows], ["Milk"])


class TestPreferredReads(unittest.TestCase):
    """get_preferred / find_by_code / options / detect_multi_p."""

    def _rows(self):
        return [
            {"row_index": 2, "name": "Eggs A", "subcategory": "eggs",
             "item_code": "ABC", "preferred": ""},
            {"row_index": 3, "name": "Milk", "subcategory": "milk",
             "item_code": "MMM", "preferred": "P"},
            {"row_index": 4, "name": "Eggs B", "subcategory": "eggs",
             "item_code": "DEF", "preferred": "P"},
        ]

    def test_get_preferred_returns_p_row(self):
        rows = [
            {"row_index": 2, "name": "Eggs A", "subcategory": "eggs",
             "item_code": "ABC", "preferred": ""},
            {"row_index": 3, "name": "Eggs B", "subcategory": "eggs",
             "item_code": "DEF", "preferred": "P"},
        ]
        got = get_preferred(rows, "eggs")
        self.assertEqual(got["item_code"], "DEF")

    def test_get_preferred_none(self):
        single = [self._rows()[0]]  # eggs row WITHOUT a P flag
        self.assertIsNone(get_preferred(single, "eggs"))
        self.assertIsNone(get_preferred(self._rows(), "bread"))

    def _corrupted_rows(self):
        """Two P flags inside "eggs" (sheet-side §8.3 corruption)."""
        return [
            {"row_index": 2, "name": "Eggs A", "subcategory": "eggs",
             "item_code": "ABC", "preferred": "P"},
            {"row_index": 3, "name": "Milk", "subcategory": "milk",
             "item_code": "MMM", "preferred": "P"},
            {"row_index": 4, "name": "Eggs B", "subcategory": "eggs",
             "item_code": "DEF", "preferred": "P"},
        ]

    def test_get_preferred_multi_p_topmost_wins_no_deletion(self):
        rows = self._corrupted_rows()  # eggs has TWO P rows
        got = get_preferred(rows, "eggs")
        self.assertEqual(got["row_index"], 2)  # topmost eggs P
        # Detection: no deletion, rows unchanged.
        self.assertEqual(len(detect_multi_p(rows)), 1)
        self.assertEqual(rows[2]["preferred"], "P")

    def test_list_subcategory_options_shape(self):
        options = list_subcategory_options(self._rows(), "eggs")
        self.assertEqual(options, [
            (2, "Eggs A", "ABC"), (4, "Eggs B", "DEF")])

    def test_detect_multi_p_finds_only_excess(self):
        report = detect_multi_p(self._corrupted_rows())
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["subcategory"], "eggs")
        self.assertEqual(len(report[0]["rows"]), 2)
        # Single-P sub-categories are NOT flagged.
        self.assertEqual(detect_multi_p(self._rows()), [])

    def test_find_by_code_case_insensitive(self):
        self.assertEqual(find_by_code(self._rows(), "abc"),
                         self._rows()[0])
        self.assertIsNone(find_by_code(self._rows(), "ZZZ"))


class TestPromptGoldens(unittest.TestCase):
    """§6.4 / §6.5 EXACT text goldens."""

    def test_prompt_exact_text(self):
        options = [
            (2, "Woolworths 12 Extra Large Free Range Eggs 700g",
             "ABC"),
            (3, "Coles 700g Free Range Eggs XL", "DEF"),
        ]
        self.assertEqual(
            render_disambiguation_prompt("eggs", options),
            "Sub-Category: eggs - Which one would you like to make "
            "your preferred item?\n"
            "1 - Woolworths 12 Extra Large Free Range Eggs 700g - "
            "ABC\n"
            "2 - Coles 700g Free Range Eggs XL - DEF\n"
            "Or: Not in list? Provide another keyword for live "
            "search.",
        )

    def test_override_warning_exact_text(self):
        self.assertEqual(
            render_override_warning("Coles 700g Free Range Eggs XL",
                                    "eggs"),
            "⚠️ Warning: [Coles 700g Free Range Eggs XL] is not your "
            "preferred item for sub-category [eggs].\n"
            "Would you like to switch your preferred item in the "
            "sheet?\n"
            "Reply 'switch' to make it preferred, or 'keep' to "
            "continue without switching.",
        )


class TestPendingIO(unittest.TestCase):
    """Pending-run file: roundtrip, corrupt, staleness."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "shop_pending.json"

    def test_pending_roundtrip_and_clear(self):
        save_pending({"started_at": "2026-09-04T10:00:00+00:00",
                      "items": ["eggs"], "halted": []},
                     path=self.path)
        loaded = load_pending(path=self.path)
        self.assertEqual(loaded["items"], ["eggs"])
        prefs.clear_pending(path=self.path)
        self.assertIsNone(load_pending(path=self.path))

    def test_pending_corrupt_reads_none(self):
        self.path.write_text("{oops", encoding="utf-8")
        self.assertIsNone(load_pending(path=self.path))

    def test_is_stale_true_after_24h(self):
        pending = {"started_at": "2026-09-03T00:00:00+00:00"}
        now = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc)
        self.assertTrue(is_stale(pending, now=now))

    def test_is_stale_false_fresh(self):
        pending = {"started_at": "2026-09-04T00:00:00+00:00"}
        now = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc)
        self.assertFalse(is_stale(pending, now=now))

    def test_is_stale_naive_timestamp_treated_as_utc(self):
        started = datetime.now(timezone.utc).replace(tzinfo=None)
        pending = {"started_at": started.isoformat()}
        self.assertFalse(is_stale(pending))

    def test_is_stale_unparsable_true(self):
        self.assertTrue(is_stale({"started_at": "not-a-date"}))


class TestSetPreferred(unittest.TestCase):
    """set_preferred: ONE range write, sibling clear, verify."""

    def _sheet(self):
        return FakeWorksheet([
            _header_a_to_s(),
            ["Eggs A", *[""] * 15, "eggs", "AAA", ""],
            ["Eggs B", *[""] * 15, "eggs", "BBB", ""],
        ])

    def test_set_preferred_sets_and_clears_sibling_one_write(self):
        ws = self._sheet()
        res = prefs.set_preferred(ws, "bbb")
        self.assertTrue(res["wrote"])
        self.assertEqual(res["cleared"], 0)
        # Exactly ONE update call, covering the sub-category span.
        self.assertEqual(len(ws.updates), 1)
        values, range_name = ws.updates[0]
        self.assertEqual(range_name, "S2:S3")
        self.assertEqual(values, [[""], ["P"]])
        # Final state via the sheet itself.
        final = read_qrs(ws)
        flags = [r["preferred"] for r in final]
        self.assertEqual(flags, ["", "P"])

    def test_set_preferred_interleaved_other_subcategory_preserved(
            self):
        ws = FakeWorksheet([
            _header_a_to_s(),
            ["Eggs A", *[""] * 15, "eggs", "AAA", ""],
            ["Milk", *[""] * 15, "milk", "MMM", "P"],
            ["Eggs B", *[""] * 15, "eggs", "BBB", ""],
        ])
        res = prefs.set_preferred(ws, "bbb")
        self.assertTrue(res["wrote"])
        # The S-vector write carries milk's P through untouched.
        _values, range_name = ws.updates[0]
        self.assertEqual(range_name, "S2:S4")
        values = ws.updates[0][0]
        self.assertEqual(values, [[""], ["P"], ["P"]])

    def test_set_preferred_unknown_code_errors(self):
        ws = self._sheet()
        res = prefs.set_preferred(ws, "ZZZ")
        self.assertFalse(res["wrote"])
        self.assertIn("ZZZ", res["error"])
        self.assertEqual(ws.updates, [])

    def test_set_preferred_row_without_subcategory_errors(self):
        ws = FakeWorksheet([
            _header_a_to_s(),
            ["Mystery", *[""] * 15, "", "AAA", ""],
        ])
        res = prefs.set_preferred(ws, "aaa")
        self.assertFalse(res["wrote"])
        self.assertIn("backfill-subcategories", res["error"])

    def test_set_preferred_empty_code_errors(self):
        ws = self._sheet()
        res = prefs.set_preferred(ws, "  ")
        self.assertFalse(res["wrote"])
        self.assertEqual(ws.updates, [])

    def test_set_preferred_verify_failure_detected(self):
        class CorruptingWorksheet(FakeWorksheet):
            """Simulates a sheet that corrupts S on every write."""

            def update(self, *, values, range_name):
                super().update(values=values, range_name=range_name)
                # Overwrite S column with garbage P flags.
                self._values[1][18] = "P"
                self._values[2][18] = "P"

        ws = CorruptingWorksheet([
            _header_a_to_s(),
            ["Eggs A", *[""] * 15, "eggs", "AAA", ""],
            ["Eggs B", *[""] * 15, "eggs", "BBB", ""],
        ])
        res = prefs.set_preferred(ws, "bbb")
        self.assertFalse(res["wrote"])
        self.assertIn("verify failed", res["error"])


class TestResolveShopItems(unittest.TestCase):
    """resolve_shop_items state machine: S0/S1/S4/S5 + multi-P."""

    def _sheet(self):
        return FakeWorksheet([
            _header_a_to_s(),
            ["Woolworths Eggs 700g", *[""] * 15, "eggs", "AAA", "P"],
            ["Coles Eggs XL", *[""] * 15, "eggs", "BBB", ""],
            ["Royal Gala Apples", *[""] * 15, "apples", "CCC", ""],
            ["Home Brand Milk", *[""] * 15, "milk", "MMM", "P"],
        ])

    def test_resolve_category_mode_with_p_autoselects(self):
        plan = prefs.resolve_shop_items(self._sheet(), ["eggs"])
        self.assertEqual(plan["compare"], [("eggs",
                                            "Woolworths Eggs 700g")])
        self.assertEqual(plan["halted"], [])

    def test_resolve_category_mode_no_p_halts_with_options(self):
        plan = prefs.resolve_shop_items(self._sheet(), ["apples"])
        self.assertEqual(plan["compare"], [])
        self.assertEqual(len(plan["halted"]), 1)
        entry = plan["halted"][0]
        self.assertEqual(entry["item"], "apples")
        self.assertEqual(entry["subcategory"], "apples")
        self.assertEqual(entry["options"],
                         [(4, "Royal Gala Apples", "CCC")])

    def test_resolve_category_mode_zero_rows_cold(self):
        plan = prefs.resolve_shop_items(self._sheet(), ["bread"])
        self.assertEqual(plan["cold"],
                         [{"item": "bread", "subcategory": "bread"}])

    def test_resolve_product_mode_warns_on_different_preferred(self):
        plan = prefs.resolve_shop_items(self._sheet(),
                                        ["coles eggs xl"])
        self.assertEqual(plan["compare"],
                         [("coles eggs xl", "Coles Eggs XL")])
        self.assertEqual(len(plan["warns"]), 1)
        self.assertEqual(plan["warns"][0]["subcategory"], "eggs")

    def test_resolve_product_mode_no_warning_when_preferred_matches(
            self):
        plan = prefs.resolve_shop_items(self._sheet(),
                                        ["woolworths eggs 700g"])
        self.assertEqual(plan["compare"],
                         [("woolworths eggs 700g",
                           "Woolworths Eggs 700g")])
        self.assertEqual(plan["warns"], [])

    def test_resolve_multi_p_note_and_topmost_wins(self):
        ws = FakeWorksheet([
            _header_a_to_s(),
            ["Eggs One", *[""] * 15, "eggs", "AAA", "P"],
            ["Eggs Two", *[""] * 15, "eggs", "BBB", "P"],
        ])
        plan = prefs.resolve_shop_items(ws, ["eggs"])
        self.assertEqual(len(plan["notes"]), 1)
        self.assertIn("2 P flags", plan["notes"][0])
        self.assertIn("AAA", plan["notes"][0])
        self.assertEqual(plan["compare"],
                         [("eggs", "Eggs One")])  # topmost wins

    def test_resolve_mixed_list_end_to_end(self):
        plan = prefs.resolve_shop_items(
            self._sheet(), ["eggs", "apples", "bread"])
        self.assertEqual(len(plan["compare"]), 1)   # eggs w/ P
        self.assertEqual(len(plan["halted"]), 1)    # apples w/o P
        self.assertEqual(len(plan["cold"]), 1)      # bread unknown
        self.assertEqual(plan["warns"], [])


class TestHalalPreferGuard(unittest.TestCase):
    """S21: set_preferred halal guard + read_qrs keywords field."""

    def _header(self):
        """A..S header but Col P carries the REAL 'Keywords' name so
        _col_index finds the halal-marker column."""
        header = _header_a_to_s()
        header[15] = "Keywords"
        return header

    def _ws(self):
        rows = [
            self._header(),
            ["Woolworths Beef Mince", "", "1kg", "12.00", "", "",
             "", "", "", "", "", "", "", "", "", "fresh",
             "beef mince", "ABC", ""],
            ["Halal Beef Mince BrandX", "", "500g", "7.50", "", "",
             "", "", "", "", "", "", "", "", "", "halal",
             "beef mince", "DEF", ""],
        ]
        return FakeWorksheet(rows)

    def test_prefer_refuses_non_marked_with_marked_sibling(self):
        """P on the NON-marked row is refused; the halal candidate
        is named in the error."""
        ws = self._ws()
        res = prefs.set_preferred(ws, "ABC")
        self.assertFalse(res["wrote"])
        self.assertIn("Halal Beef Mince BrandX", res["error"])
        self.assertIn("set P there instead", res["error"])

    def test_prefer_refuses_in_any_subcategory_manual_marker(self):
        """The guard applies to ANY sub-category (manual markers)."""
        rows = [
            self._header(),
            ["Plain Yoghurt", "", "1kg", "3.00", "", "", "", "", "",
             "", "", "", "", "", "", "fresh", "greek yoghurt",
             "GHI", ""],
            ["Halal Yoghurt Co", "", "1kg", "3.50", "", "", "", "",
             "", "", "", "", "", "", "", "halal", "greek yoghurt",
             "JKL", ""],
        ]
        ws = FakeWorksheet(rows)
        res = prefs.set_preferred(ws, "GHI")
        self.assertFalse(res["wrote"])
        self.assertIn("Halal Yoghurt Co", res["error"])

    def test_prefer_allows_when_no_marked_sibling(self):
        """No marked sibling -> P writes normally."""
        rows = [
            self._header(),
            ["Plain Yoghurt", "", "1kg", "3.00", "", "", "", "", "",
             "", "", "", "", "", "", "fresh", "greek yoghurt",
             "GHI", ""],
        ]
        ws = FakeWorksheet(rows)
        res = prefs.set_preferred(ws, "GHI")
        self.assertTrue(res["wrote"])

    def test_prefer_allows_marked_row_itself(self):
        """Setting P ON the halal-marked row itself is allowed."""
        ws = self._ws()
        res = prefs.set_preferred(ws, "DEF")
        self.assertTrue(res["wrote"])

    def test_read_qrs_exposes_keywords_field(self):
        """read_qrs rows carry the Col P keywords verbatim."""
        ws = self._ws()
        rows = prefs.read_qrs(ws)
        self.assertEqual(rows[0]["keywords"], "fresh")
        self.assertEqual(rows[1]["keywords"], "halal")

    def test_multiple_marked_rows_prefer_still_writes_and_backfill_surfaces(
            self):
        """Two marked rows in one sub-category: prefer on one still
        writes; detect_multi_p surfaces the duplicate (not guessed)."""
        rows = [
            self._header(),
            ["Halal Beef A", "", "1kg", "12.00", "", "", "", "", "",
             "", "", "", "", "", "", "halal", "beef mince",
             "AAA", "P"],
            ["Halal Beef B", "", "1kg", "12.50", "", "", "", "", "",
             "", "", "", "", "", "", "halal", "beef mince",
             "BBB", "P"],
        ]
        ws = FakeWorksheet(rows)
        # Pre-state: two P flags in one sub-category -> surfaced by
        # detect_multi_p (reported, never silently guessed).
        multi = prefs.detect_multi_p(prefs.read_qrs(ws))
        self.assertEqual(len(multi), 1)
        self.assertEqual(multi[0]["subcategory"], "beef mince")
        # prefer on a MARKED row with a marked sibling still writes;
        # the single-writer clears the sibling (cleared=1).
        res = prefs.set_preferred(ws, "BBB")
        self.assertTrue(res["wrote"])
        self.assertEqual(res["cleared"], 1)


if __name__ == "__main__":
    unittest.main()
