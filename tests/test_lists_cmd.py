#!/usr/bin/env python3
"""Tests for the live `lists` command + mid-week .txt resolution removal.

Sandboxed (2026-09-03 rule): every test writes ONLY to tmp dirs — the
real grocery-price-tracker/data/ folder is never touched. The sheet is
a FakeWorksheet; queues and debt storage are monkeypatched.
"""
from __future__ import annotations
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))
_ROOT = _PROJECT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import grocery_price_cli as gcli  # noqa: E402


# ============================================================================
# Fakes
# ============================================================================

class FakeWorksheet:
    """Minimal gspread Worksheet stand-in (get_all_values only)."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]

    def get_all_values(self):
        return [list(r) for r in self._values]


def _row(generic, size, ww_price, coles_price, ww_kw, coles_kw,
         last_updated="2026-09-01 10:00"):
    """Build a 10-col Products_Master row (A..J)."""
    return [generic, "", size, ww_price, coles_price, "", "",
            last_updated, ww_kw, coles_kw]


_SHEET_ROWS = [
    _row("Name", "Size", "WW", "Coles", "I", "J"),          # header
    _row("Milk 2L", "2L", "3.50", "3.60", "milk 2l", ""),   # coles-missing
    _row("Bread White", "600g", "4.00", "4.20", "", "bread white"),  # wool-missing
    _row("Juice Orange", "1L", "3.00", "N/A 2026-08-01",
         "juice orange", "NA"),                              # NA -> excluded
    _row("Old Thing", "500g", "N/A 2026-08-01", "N/A 2026-08-01",
         "old thing", "old thing coles"),                    # no-price only
    _row("Oat Milk 1L", "1L", "5.00", "5.10",
         "oat milk 1l", "oat milk 1l coles"),                # fully priced
    # CROSSED (matrix scenario 9): WW kw + dead WW price, Coles kw
    # empty + good Coles price -> coles-missing AND missed-pricing
    _row("Crossed Item", "500g", "N/A 2026-08-20", "3.60",
         "ww kw", ""),
    ["", "", "", "", "", "", "", "", "", ""],                # blank -> skipped
]

_PENDING_DEBT = [
    {"raw_name": "Oat Milk 1L", "store": "woolworths"},   # keyword exists
    {"raw_name": "Junk Line", "store": "woolworths"},     # ignored
    {"raw_name": "Mystery Item", "store": "woolworths"},  # genuinely pending
]


def _make_data_dir(tmp: Path) -> Path:
    """Create a sandbox data dir with an ignored_items.txt file."""
    data = tmp / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "ignored_items.txt").write_text(
        "# ignored\n\nJunk Line [woolworths]\n", encoding="utf-8")
    return data


# ============================================================================
# lists — live counts
# ============================================================================

class TestListsCommand(unittest.TestCase):

    def _run_lists(self, tmp: Path, ws=None, sheet_error=None, full=False,
                   pending_adds=None):
        """Run _cmd_lists fully sandboxed; returns (stdout, exit_code).

        pending_adds: set of (store, generic) that is_pending reports as
        queued website-adds (None -> nothing pending).
        """
        args = MagicMock(full=full)
        queue_a = MagicMock(return_value=[
            {"keyword": "milk", "size": "2L", "store": "coles",
             "code": "MLK"}])
        queue_s = MagicMock(return_value=[
            {"keyword": "bread", "size": "600g", "store": "woolworths",
             "code": "BRD"}])
        connect = MagicMock(return_value=ws)
        if sheet_error is not None:
            connect.side_effect = sheet_error
        pending = MagicMock(return_value=list(_PENDING_DEBT))
        is_pend = MagicMock(
            side_effect=lambda store, generic:
                ({"store": store, "generic_name": generic}
                 if (store, generic) in (pending_adds or set()) else None))

        with patch.object(gcli, "_TRACKER", tmp), \
                patch.object(gcli, "_load_env"), \
                patch("core.sheets_client.connect_worksheet", connect), \
                patch("core.name_matcher.get_pending_mappings", pending), \
                patch("core.add_to_list.ordered_entries", queue_a), \
                patch("core.add_to_list.is_pending", is_pend), \
                patch("core.searched_items.ordered_entries", queue_s):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = gcli._cmd_lists(args)
        return buf.getvalue(), code

    def test_counts_are_live(self):
        """All 6 counts computed from the fake sheet + the to-do queue."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_data_dir(tmp)
            out, code = self._run_lists(
                tmp, ws=FakeWorksheet(_SHEET_ROWS))
            self.assertEqual(code, 0)
            self.assertIn("1. Unmatched — 1", out)      # Mystery Item only
            self.assertIn("2. Woolworths missing — 1", out)  # Bread White
            # Crossed Item: coles-missing AND fixable -> overlap note
            self.assertIn("3. Coles missing — 2 "
                          "(1 also in missed pricing)", out)
            self.assertIn("4. To-do (website adds) — 1", out)
            self.assertIn("5. Forgotten/ignored — 1", out)
            # Crossed Item joined the fixable group: 1 + crossed = 2
            self.assertIn(
                "6. Missed pricing — 3 (2 fixable · 1 delete-pending)",
                out)  # Old Thing

    def test_na_keyword_excluded_from_missing(self):
        """A row with keyword 'NA' counts as populated (Wednesday rule)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_data_dir(tmp)
            out, _ = self._run_lists(tmp, ws=FakeWorksheet(_SHEET_ROWS))
            # Juice Orange must NOT appear as missing (its Coles kw is NA)
            # -> Coles missing stays at Milk 2L + Crossed Item = 2
            self.assertNotIn("3. Coles missing — 3", out)
            self.assertNotIn("2. Woolworths missing — 2", out)

    def test_full_prints_names(self):
        """--full prints the item names under each count."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_data_dir(tmp)
            out, code = self._run_lists(
                tmp, ws=FakeWorksheet(_SHEET_ROWS), full=True)
            self.assertEqual(code, 0)
            self.assertIn("Mystery Item [woolworths]", out)
            self.assertIn("Bread White", out)
            self.assertIn("Milk 2L", out)
            self.assertIn("Old Thing", out)
            # Cross-list marker on the missing list entry
            self.assertIn("Crossed Item", out)
            self.assertIn("⚠ also in missed pricing", out)

    def test_sheet_failure_degrades_not_crashes(self):
        """Sheet read failure -> lists 1/2/3/7 unavailable, queues still
        shown, exit 0, verbatim error surfaced."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_data_dir(tmp)
            out, code = self._run_lists(
                tmp, sheet_error=RuntimeError("boom 503"))
            self.assertEqual(code, 0)
            self.assertIn("1. Unmatched — unavailable", out)
            self.assertIn("2. Woolworths missing — unavailable", out)
            self.assertIn("3. Coles missing — unavailable", out)
            self.assertIn("6. Missed pricing — unavailable", out)
            self.assertIn("4. To-do (website adds) — 1", out)
            self.assertIn("Sheet read failed", out)
            self.assertIn("boom 503", out)

    def test_resolved_debt_not_counted(self):
        """Debt entries whose keyword now exists are resolved, not listed."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_data_dir(tmp)
            out, _ = self._run_lists(tmp, ws=FakeWorksheet(_SHEET_ROWS))
            self.assertNotIn("Oat Milk 1L [woolworths]", out)

    def test_pending_website_add_annotated(self):
        """A missing row with a queued website add is annotated in the
        count line and its --full item line (handshake, not a dupe)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_data_dir(tmp)
            out, _ = self._run_lists(
                tmp, ws=FakeWorksheet(_SHEET_ROWS), full=True,
                pending_adds={("coles", "Milk 2L")})
            self.assertIn("3. Coles missing — 2 (1 pending website add "
                          "· 1 also in missed pricing)", out)
            # The --full line carries the queue marker
            self.assertIn("⏳ website add queued", out)
            # Woolworths missing item has no add queued -> no annotation
            self.assertIn("2. Woolworths missing — 1", out)
            self.assertNotIn("2. Woolworths missing — 1 (", out)

    def test_no_annotation_without_pending_adds(self):
        """No website-add parenthetical when no missing row has a
        queued add (the missed-pricing overlap note may still show)."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_data_dir(tmp)
            out, _ = self._run_lists(tmp, ws=FakeWorksheet(_SHEET_ROWS))
            self.assertIn(
                "3. Coles missing — 2 (1 also in missed pricing)", out)
            self.assertNotIn("pending website add", out)


# ============================================================================
# Mid-week .txt resolution removal
# ============================================================================

class TestRemoveResolvedLine(unittest.TestCase):

    def _write_list(self, data: Path, fname: str, items):
        (data / fname).write_text(
            f"# Header — {len(items)} total\n\n" +
            "\n".join(items) + "\n", encoding="utf-8")

    def test_removes_line_and_updates_header(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            self._write_list(data, "unmatched.txt",
                             ["A [woolworths]", "B [coles]", "C [coles]"])
            removed = gcli._remove_resolved_line(
                data, "unmatched", "B [coles]")
            self.assertTrue(removed)
            text = (data / "unmatched.txt").read_text(encoding="utf-8")
            self.assertNotIn("B [coles]", text)
            self.assertIn("A [woolworths]", text)
            self.assertIn("C [coles]", text)
            self.assertIn("2 total", text)

    def test_missing_line_is_noop(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            self._write_list(data, "coles_missing.txt", ["Milk 2L"])
            removed = gcli._remove_resolved_line(
                data, "coles", "Not There")
            self.assertFalse(removed)
            self.assertIn("Milk 2L",
                          (data / "coles_missing.txt").read_text(
                              encoding="utf-8"))

    def test_unknown_list_name_is_noop(self):
        with tempfile.TemporaryDirectory() as td:
            removed = gcli._remove_resolved_line(
                Path(td), "bogus", "X")
            self.assertFalse(removed)


class TestAdvanceAndShowResolved(unittest.TestCase):

    def _setup(self, tmp: Path, items):
        data = tmp / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "unmatched.txt").write_text(
            f"# Header — {len(items)} total\n\n" + "\n".join(items) + "\n",
            encoding="utf-8")
        progress_path = data / "list_action_progress.json"
        return data, progress_path

    def test_resolved_keeps_index_and_removes_line(self):
        """resolved=True: line leaves the file, progress stays at idx so
        the NEXT item (not the one after) is shown."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            items = ["A [woolworths]", "B [coles]", "C [coles]"]
            data, progress_path = self._setup(tmp, items)
            progress = {"unmatched": 0, "wool": 0, "coles": 0}
            shown = []
            with patch.object(gcli, "_resolve_and_print_unmatched",
                              side_effect=lambda eng, it: shown.append(it)):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = gcli._advance_and_show(
                        "unmatched", items, 0, progress,
                        progress_path, data, resolved=True)
            self.assertEqual(code, 0)
            self.assertEqual(shown, ["B [coles]"])  # next item, not C
            self.assertEqual(progress["unmatched"], 0)  # idx unchanged
            text = (data / "unmatched.txt").read_text(encoding="utf-8")
            self.assertNotIn("A [woolworths]", text)
            self.assertIn("2 total", text)

    def test_skip_still_advances_without_removal(self):
        """resolved=False keeps the legacy behaviour: line stays,
        pointer advances past it."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            items = ["A [woolworths]", "B [coles]"]
            data, progress_path = self._setup(tmp, items)
            progress = {"unmatched": 0, "wool": 0, "coles": 0}
            shown = []
            with patch.object(gcli, "_resolve_and_print_unmatched",
                              side_effect=lambda eng, it: shown.append(it)):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    gcli._advance_and_show(
                        "unmatched", items, 0, progress,
                        progress_path, data)
            self.assertEqual(shown, ["B [coles]"])
            self.assertEqual(progress["unmatched"], 1)
            text = (data / "unmatched.txt").read_text(encoding="utf-8")
            self.assertIn("A [woolworths]", text)  # line kept

    def test_resolved_last_item_completes(self):
        """Resolving the final item ends the list cleanly."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            items = ["Only [woolworths]"]
            data, progress_path = self._setup(tmp, items)
            progress = {"unmatched": 0, "wool": 0, "coles": 0}
            with patch.object(gcli, "_resolve_and_print_unmatched"):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = gcli._advance_and_show(
                        "unmatched", items, 0, progress,
                        progress_path, data, resolved=True)
            self.assertEqual(code, 0)
            self.assertIn("resolved!", buf.getvalue())


class TestListsQRSSurfacing(unittest.TestCase):
    """needs-review + multi-P surfacing in `lists` (S23, §8.3/D-SC2)."""

    def _qrs_row(self, generic, subcategory="", preferred=""):
        """19-col row (A..S): name, then prices/keywords empty except
        a usable WW price so the row parses like normal data."""
        row = [generic, "", "1L", "3.50", "3.60", "", "",
               "2026-09-01 10:00", "kw", "kw coles"]
        row += [""] * 6                                   # K..P
        row += [subcategory, "", preferred]               # Q, R, S
        return row

    def _run_lists(self, tmp: Path, ws=None, sheet_error=None,
                   full=False, todo_entries=None):
        args = MagicMock(full=full)
        queue_a = MagicMock(return_value=list(todo_entries or []))
        queue_s = MagicMock(return_value=[])
        connect = MagicMock(return_value=ws)
        if sheet_error is not None:
            connect.side_effect = sheet_error
        pending = MagicMock(return_value=[])
        with patch.object(gcli, "_TRACKER", tmp), \
                patch.object(gcli, "_load_env"), \
                patch("core.sheets_client.connect_worksheet", connect), \
                patch("core.name_matcher.get_pending_mappings", pending), \
                patch("core.add_to_list.ordered_entries", queue_a), \
                patch("core.add_to_list.is_pending", MagicMock(
                    return_value=None)), \
                patch("core.searched_items.ordered_entries", queue_s):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = gcli._cmd_lists(args)
        return buf.getvalue(), code

    @staticmethod
    def _with_header(rows):
        """_cmd_lists treats sheet row 1 as the header — prepend one."""
        header = ["Product_Name", "", "Size", "WW", "Coles", "", "",
                  "Last_Updated", "I", "J"] + [""] * 6 + \
                 ["Sub_Category", "Item_Code", "Preferred"]
        return [header, *rows]

    def test_lists_shows_needs_review_count(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rows = [
                self._qrs_row("Milk 2L"),
                self._qrs_row("Mystery Goo", subcategory="needs review"),
                self._qrs_row("Odd Paste", subcategory="Needs Review"),
            ]
            out, code = self._run_lists(
                tmp, ws=FakeWorksheet(self._with_header(rows)))
            self.assertEqual(code, 0)
            # List 7 (user rule 2026-09-05): sub-category reviews.
            self.assertIn("7. Sub-category reviews — 2", out)
            self.assertIn("Sub-category reviews — 2 row(s) need "
                          "your call", out)

    def test_lists_warns_on_multi_p(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rows = [
                self._qrs_row("Eggs One", subcategory="eggs",
                              preferred="P"),
                self._qrs_row("Eggs Two", subcategory="eggs",
                              preferred="P"),
                self._qrs_row("Milk 2L", subcategory="milk",
                              preferred="P"),  # single P: silent
            ]
            out, code = self._run_lists(
                tmp, ws=FakeWorksheet(self._with_header(rows)))
            self.assertEqual(code, 0)
            self.assertIn("sub-category 'eggs' has 2 P flags", out)
            self.assertNotIn("'milk' has", out)

    def test_lists_silent_when_clean(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rows = [
                self._qrs_row("Milk 2L", subcategory="milk",
                              preferred="P"),
                self._qrs_row("Bread 600g", subcategory="bread"),
            ]
            out, code = self._run_lists(
                tmp, ws=FakeWorksheet(self._with_header(rows)))
            self.assertEqual(code, 0)
            self.assertNotIn("needs review", out)
            self.assertNotIn("P flags", out)

    def test_lists_full_marks_multibuy_todo_and_reviews(self):
        """USER RULE 2026-09-05: --full renders ' (m)' + the legend on
        to-do entries whose sheet row is on a multi-buy deal, and a
        SUB-CATEGORY REVIEWS block naming the unsure rows."""
        rows = [
            self._qrs_row("Milk Deal", subcategory="milk"),
            self._qrs_row("Mystery Goo", subcategory="needs review"),
        ]
        # Put the WW row on a multi-buy deal (Col M, idx 12).
        rows[0][12] = "multi-buy 2/$7.00"
        todo = [{
            "store": "woolworths", "keyword": "KW Deal Milk",
            "generic_name": "Milk Deal", "size": "2L", "code": "MBD",
        }]
        out, code = self._run_lists(
            Path(tempfile.gettempdir()),
            ws=FakeWorksheet(self._with_header(rows)),
            full=True, todo_entries=todo)
        self.assertEqual(code, 0)
        # (m) on the deal line + the legend underneath.
        self.assertRegex(out, r"KW Deal Milk[^\n]*\(m\)")
        self.assertIn("(m) - multi buy discount", out)
        # Sub-category reviews block names the unsure row.
        self.assertIn("SUB-CATEGORY REVIEWS", out)
        self.assertIn("Mystery Goo", out)

    def test_lists_full_no_m_without_deal(self):
        """No multi-buy cells -> no (m) mark and no legend."""
        rows = [self._qrs_row("Milk 2L", subcategory="milk")]
        todo = [{
            "store": "woolworths", "keyword": "kw", "generic_name": "Milk 2L",
            "size": "", "code": "PLN",
        }]
        out, code = self._run_lists(
            Path(tempfile.gettempdir()),
            ws=FakeWorksheet(self._with_header(rows)),
            full=True, todo_entries=todo)
        self.assertEqual(code, 0)
        self.assertNotIn("(m)", out)


if __name__ == "__main__":
    unittest.main()
