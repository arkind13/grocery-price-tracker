#!/usr/bin/env python3
"""Unified `todo` queue tests (to-do + searched merged, uniform done).

Sandboxed: queue paths patched to temp files; sheet keyword writes
mocked. The real data/ folder is never touched.
"""
from __future__ import annotations
import contextlib
import io
import json
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
from core import add_to_list as atl  # noqa: E402
from core import searched_items as si  # noqa: E402


def _write_queue(path: Path, entries: list) -> None:
    path.write_text(json.dumps(entries), encoding="utf-8")


class TodoTestCase(unittest.TestCase):
    """Base: both queues isolated in a temp dir + keyword write mock."""

    ADDS = [  # add-to-list entries (price written, keyword pending)
        {"store": "coles", "keyword": "Coles Up&Go Choc 500mL",
         "generic_name": "Up&Go Chocolate Protein 500Ml",
         "size": "500mL", "code": "HUY", "added_at": "2026-09-01T00:00:00"},
        {"store": "woolworths", "keyword": "Birkford Iced Mocha 500mL",
         "generic_name": "Birkford Iced Mocha",
         "size": "500mL", "code": "MUY", "added_at": "2026-09-02T00:00:00"},
    ]
    SEARCHED = [  # searched entries (new row, keyword empty)
        {"store": "coles", "keyword": "Coles Raw Sugar 2kg",
         "generic_name": "Coles Raw Sugar 2kg",
         "size": "2kg", "code": "EDA", "added_at": "2026-09-03T00:00:00"},
        {"store": "woolworths", "keyword": "WW Basmati Rice 250g",
         "generic_name": "WW Basmati Rice 250g",
         "size": "250g", "code": "SRM", "added_at": "2026-09-03T00:00:00"},
    ]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.adds_path = tmp / "add_to_list.json"
        self.searched_path = tmp / "searched_items.json"
        self.si_tomb = tmp / "si_tombstones.json"
        self.atl_tomb = tmp / "atl_tombstones.json"
        _write_queue(self.adds_path, list(self.ADDS))
        _write_queue(self.searched_path, list(self.SEARCHED))
        self._patchers = [
            patch.object(atl, "ADD_TO_LIST_PATH", self.adds_path),
            patch.object(atl, "A_L_TOMBSTONES_PATH", self.atl_tomb),
            patch.object(si, "SEARCHED_ITEMS_PATH", self.searched_path),
            patch.object(si, "TOMBSTONES_PATH", self.si_tomb),
        ]
        for p in self._patchers:
            p.start()
            self.addCleanup(p.stop)
        self.kw_writes = MagicMock(
            return_value={"found": True, "row_index": 42})

    def _run(self, action, items=None):
        args = MagicMock(action=action, items=items)
        with patch("core.sheets_sync.set_store_keyword", self.kw_writes):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = gcli._cmd_todo(args)
        return buf.getvalue(), code

    def _queue(self, path):
        return json.loads(path.read_text(encoding="utf-8"))


class TestTodoShow(TodoTestCase):

    def test_merged_view_continuous_numbering(self):
        """Coles adds, Coles searched, WW adds, WW searched — one list."""
        out, code = self._run("show")
        self.assertEqual(code, 0)
        self.assertIn("1. Coles Up&Go Choc 500mL · 500mL (Coles) [HUY]", out)
        self.assertIn("2. Coles Raw Sugar 2kg · 2kg (Coles) [EDA] · new row",
                      out)
        self.assertIn(
            "3. Birkford Iced Mocha 500mL · 500mL "
            "(Woolworths) [MUY]", out)
        self.assertIn(
            "4. WW Basmati Rice 250g · 250g "
            "(Woolworths) [SRM] · new row", out)
        self.assertIn("4 pending (2 price-pending · 2 new rows)", out)

    def test_empty_queue(self):
        _write_queue(self.adds_path, [])
        _write_queue(self.searched_path, [])
        out, code = self._run("show")
        self.assertEqual(code, 0)
        self.assertIn("none", out)


class TestTodoDone(TodoTestCase):

    def test_done_by_merged_number_and_code_writes_keywords(self):
        """done 2,SRM: searched-by-number (EDA) + searched-by-code
        (SRM) — BOTH get their keyword written (the gap fix); the
        add-to-list queue is untouched."""
        out, code = self._run("done", "2,SRM")
        self.assertEqual(code, 0)
        remaining = self._queue(self.searched_path)
        self.assertEqual(remaining, [])
        written = [(c.args[0], c.args[1], c.args[2])
                   for c in self.kw_writes.call_args_list]
        self.assertIn(
            ("Coles Raw Sugar 2kg", "coles", "Coles Raw Sugar 2kg"), written)
        self.assertIn(
            ("WW Basmati Rice 250g", "woolworths",
             "WW Basmati Rice 250g"), written)
        self.assertIn("2 keyword(s) saved", out)
        # adds untouched
        self.assertEqual(len(self._queue(self.adds_path)), 2)

    def test_done_add_entry_uses_remembered_store_name(self):
        """done HUY: add-type — keyword = remembered exact store name,
        not the generic name."""
        out, code = self._run("done", "HUY")
        self.assertEqual(code, 0)
        written = [(c.args[0], c.args[1], c.args[2])
                   for c in self.kw_writes.call_args_list]
        self.assertIn(
            ("Up&Go Chocolate Protein 500Ml", "coles",
             "Coles Up&Go Choc 500mL"), written)
        self.assertEqual(len(self._queue(self.adds_path)), 1)

    def test_done_mixed_types(self):
        """1,HUY + 4,EDA across both queues in one call."""
        out, code = self._run("done", "1,4")
        self.assertEqual(code, 0)
        self.assertEqual(len(self._queue(self.adds_path)), 1)
        self.assertEqual(len(self._queue(self.searched_path)), 1)
        self.assertIn("2 item(s) removed, 2 keyword(s) saved", out)

    def test_unknown_code_all_or_nothing(self):
        """A bad code aborts with NO mutation on either queue."""
        out, code = self._run("done", "HUY,ZZZ")
        self.assertEqual(code, 1)
        self.assertEqual(len(self._queue(self.adds_path)), 2)
        self.assertEqual(len(self._queue(self.searched_path)), 2)
        self.assertEqual(self.kw_writes.call_count, 0)

    def test_row_not_found_still_removes(self):
        """Keyword write failure (row deleted) removes the entry anyway."""
        self.kw_writes = MagicMock(
            return_value={"found": False, "error": "not found"})
        out, code = self._run("done", "MUY")
        self.assertEqual(code, 0)
        self.assertEqual(len(self._queue(self.adds_path)), 1)
        self.assertIn("not written", out)


class TestTodoGone(TodoTestCase):
    """User rule 2026-09-03: 'mark item N GONE' = keyword LEFT ALONE,
    store price cell written GONE, entry removed from the queue."""

    def _run_gone(self, items):
        args = MagicMock(action="gone", items=items)
        self.gone_writes = MagicMock(
            return_value={"found": True, "wrote": True, "row_index": 42})
        with patch("core.sheets_sync.mark_price_gone", self.gone_writes), \
                patch("core.sheets_sync.set_store_keyword", self.kw_writes):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = gcli._cmd_todo(args)
        return buf.getvalue(), code

    def test_gone_marks_price_cell_never_touches_keyword(self):
        out, code = self._run_gone("HUY")
        self.assertEqual(code, 0)
        # Coles generic name + store passed to the GONE write.
        self.gone_writes.assert_called_once_with(
            "Up&Go Chocolate Protein 500Ml", "coles")
        # The keyword write is NEVER called on a gone.
        self.assertEqual(self.kw_writes.call_count, 0)
        # Entry removed from the queue.
        remaining = self._queue(self.adds_path)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["code"], "MUY")
        self.assertIn("marked GONE", out)
        self.assertIn("keywords untouched", out)

    def test_gone_mixed_queues_all_or_nothing(self):
        """1,SRM spans both queues; a bad extra code aborts everything."""
        out, code = self._run_gone("1,SRM,ZZZ")
        self.assertEqual(code, 1)
        self.assertEqual(len(self._queue(self.adds_path)), 2)
        self.assertEqual(len(self._queue(self.searched_path)), 2)
        self.assertEqual(self.gone_writes.call_count, 0)

    def test_gone_row_not_found_still_removes(self):
        """Sheet row already gone: entry still leaves the queue."""
        self.gone_writes = MagicMock(
            return_value={"found": False, "wrote": False,
                          "error": "product not found"})
        args = MagicMock(action="gone", items="EDA")
        with patch("core.sheets_sync.mark_price_gone", self.gone_writes), \
                patch("core.sheets_sync.set_store_keyword", self.kw_writes):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = gcli._cmd_todo(args)
        self.assertEqual(code, 0)
        self.assertEqual(len(self._queue(self.searched_path)), 1)
        self.assertIn("GONE not written", buf.getvalue())

    def test_gone_requires_items(self):
        args = MagicMock(action="gone", items=None)
        self.gone_writes = MagicMock()
        with patch("core.sheets_sync.mark_price_gone", self.gone_writes), \
                patch("core.sheets_sync.set_store_keyword", self.kw_writes):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = gcli._cmd_todo(args)
        self.assertEqual(code, 1)
        self.assertIn("'todo gone' requires --items", err.getvalue())
        self.assertEqual(self.gone_writes.call_count, 0)


class TestSearchMergeQueuesTodo(unittest.TestCase):
    """The basmati gap fix: a merged search-add with an empty store
    keyword queues a to-do entry with the exact store name."""

    def _run_add(self, merged_result, store="coles"):
        chosen = MagicMock(
            raw_name="Coles Microwave Basmati Rice 250g", price=2.9,
            brand="", category="", size="250g", is_special=False,
            special_desc="", product_id="x", store="Coles")
        args = MagicMock(add_item=1, expand=False, unit="250g",
                         allow_duplicate=False, product="basmati rice")
        displayed = [chosen]
        with patch.object(gcli, "_load_env"), \
                patch.object(gcli, "_resolve_add_unit",
                             MagicMock(return_value="250g")), \
                patch("core.sheets_sync.add_product_row",
                      MagicMock(return_value=merged_result)), \
                patch.object(gcli, "_queue_add_to_list") as q:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                # re-run the add path on a synthetic args/displayed
                code = gcli._search_add_item(args, "basmati rice", displayed)
        return buf.getvalue(), code, q

    def test_merged_empty_keyword_queues_todo(self):
        res = {"merged": True, "wrote": True, "row_index": 82,
               "existing_name": "Woolworths Microwave Basmati Rice 250g",
               "store_keyword_empty": True}
        out, code, queued = self._run_add(res)
        self.assertEqual(code, 0)
        queued.assert_called_once_with(
            "coles", "Woolworths Microwave Basmati Rice 250g",
            "Coles Microwave Basmati Rice 250g", size="250g")
        self.assertIn("TO-DO", out)

    def test_merged_keyword_present_no_queue(self):
        res = {"merged": True, "wrote": True, "row_index": 82,
               "existing_name": "Some Row",
               "store_keyword_empty": False}
        out, code, queued = self._run_add(res)
        self.assertEqual(code, 0)
        queued.assert_not_called()


if __name__ == "__main__":
    unittest.main()
