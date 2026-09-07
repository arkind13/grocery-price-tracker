#!/usr/bin/env python3
"""Basket confirmation-flow tests (pre-basket live-search confirm).

User decision tree (final, 2026-09-03):
  1. fully sheet-priced            -> straight to basket (no entry)
  2. one store priced:
     a. other-side KEYWORD missing + already queued on searched/to-do
        -> action "queued" (info only, no action)
     b. other-side PRICING missing/error -> closest sheet substitute
        first (read-only, source "sub") -> else live search with a
        PRICE-ONLY write into the existing row (keyword never written;
        item stays flagged on the wool/coles missing list)
  3. row exists, neither priced    -> same as 2b for both sides
  4. not on the sheet              -> confirmable; compare-only by
     default, "+add" opts in to new row + searched-list entries

Extractors and sheet writers are patched at the module boundary — no
network, no real sheet.
"""
from __future__ import annotations
import argparse
import contextlib
import io
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
_ROOT = _PROJECT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.price_comparator import BasketItem  # noqa: E402
from core import basket_confirm as bc  # noqa: E402

CODE_ALPHABET = set(bc.CODE_ALPHABET)


def _sheet_item(name, ww=None, coles=None):
    """BasketItem from a sheet pass (no matched names — sheet mode)."""
    prices = {}
    sources = {}
    if ww is not None:
        prices["woolworths"] = ww
        sources["woolworths"] = "sheet"
    if coles is not None:
        prices["coles"] = coles
        sources["coles"] = "sheet"
    return BasketItem(name=name, prices=prices, sources=sources)


def _live(name, price, size="500g"):
    """ProductItem-like live result (rank/pair need raw_name+size)."""
    return SimpleNamespace(raw_name=name, price=price, size=size,
                           brand="Acme", category="",
                           product_id="123456", is_special=False,
                           special_desc="")


def _stub_live(ww_items, coles_items, coles_status="ok"):
    def stub_ww(query, page_size=5):
        return list(ww_items)

    def stub_coles(query, page_size=5):
        return (list(coles_items), coles_status)

    return patch(
        "extractors.woolworths_extractor.fetch_woolworths_search_noauth",
        side_effect=stub_ww), patch(
        "extractors.coles_extractor.fetch_coles_search_status",
        side_effect=stub_coles)


class _FakeIdx:
    """Minimal LookupIndex stand-in for substitute searches."""

    def __init__(self, rows):
        self._rows = rows  # dicts: row_index/generic_name/prices

    def find_candidates(self, query, limit=5):
        q_tokens = [t for t in query.lower().split() if len(t) >= 4]
        out = []
        for r in self._rows:
            name_tokens = r["generic_name"].lower().split()
            if any(any(t.startswith(q) or q.startswith(t)
                       for t in name_tokens) for q in q_tokens):
                out.append(SimpleNamespace(
                    row_index=r["row_index"],
                    generic_name=r["generic_name"], brand="",
                    size="", score=1))
        return out

    def get_row(self, row_index):
        for r in self._rows:
            if r["row_index"] == row_index:
                return r
        return None


class TestCodesAndParse(unittest.TestCase):
    """Pending-code assignment + --confirm grammar."""

    def test_codes_unique_alphabet_three_chars(self):
        gaps = [{"keyword": f"item{i}", "group": "C", "row_name": "",
                 "row_index": None} for i in range(25)]
        coded = bc.assign_codes(gaps)
        codes = [g["code"] for g in coded]
        self.assertEqual(len(codes), len(set(codes)))
        for code in codes:
            self.assertEqual(len(code), 3)
            self.assertTrue(set(code) <= CODE_ALPHABET)

    def test_parse_all_none_and_codes(self):
        codes, adds, err = bc.parse_confirm("all", ["KAT", "ABC"])
        self.assertEqual((codes, adds, err),
                         ({"KAT", "ABC"}, set(), ""))
        codes, adds, err = bc.parse_confirm("none", ["KAT"])
        self.assertEqual((codes, adds, err), (set(), set(), ""))
        codes, adds, err = bc.parse_confirm("all+add", ["KAT"])
        self.assertEqual(codes, {"KAT"})
        self.assertEqual(adds, {"KAT"})

    def test_parse_codes_with_add_suffix(self):
        codes, adds, err = bc.parse_confirm("kat+add, ABC",
                                            ["KAT", "ABC"])
        self.assertEqual(codes, {"KAT", "ABC"})
        self.assertEqual(adds, {"KAT"})
        self.assertEqual(err, "")

    def test_parse_unknown_code_lists_pending(self):
        codes, adds, err = bc.parse_confirm("ZZZ", ["KAT"])
        self.assertEqual((codes, adds), (set(), set()))
        self.assertIn("ZZZ", err)


class TestClassification(unittest.TestCase):
    """The decision tree — groups, actions, substitutes, queues."""

    def test_groups_and_no_action_items(self):
        items = [
            _sheet_item("ww_only", ww=2.0),          # A (live)
            _sheet_item("coles_only", coles=3.0),    # B (live)
            _sheet_item("both", ww=1.0, coles=1.0),  # no entry
            _sheet_item("ghost"),                    # C-new (live)
            _sheet_item("legacy_row"),               # C-row (live)
        ]
        rows = {
            "legacy_row": {"row_index": 9,
                           "generic_name": "Legacy Bread 650g",
                           "prices": {}, "ww_kw": "", "coles_kw": ""},
            # ww_only has BOTH keywords -> pricing missing (not queued)
            "ww_only": {"row_index": 4, "generic_name": "WW Only Row",
                        "prices": {"woolworths": 2.0},
                        "ww_kw": "ww kw", "coles_kw": "coles kw"},
            # coles_only: WW keyword missing (B-side gap)
            "coles_only": {"row_index": 6,
                           "generic_name": "Coles Only Row",
                           "prices": {"coles": 3.0},
                           "ww_kw": "", "coles_kw": "coles kw"},
        }
        items, entries = bc.classify_basket(items, rows, idx=None)
        by_kw = {e["keyword"]: e for e in entries}
        self.assertEqual(by_kw["ww_only"]["group"], "A")
        self.assertEqual(by_kw["ww_only"]["action"], "live")
        self.assertEqual(by_kw["coles_only"]["group"], "B")
        self.assertEqual(by_kw["coles_only"]["action"], "live")
        self.assertNotIn("both", by_kw)
        self.assertEqual(by_kw["ghost"]["group"], "C")
        self.assertEqual(by_kw["ghost"]["row_name"], "")
        self.assertEqual(by_kw["legacy_row"]["group"], "C")
        self.assertEqual(by_kw["legacy_row"]["row_name"],
                         "Legacy Bread 650g")

    def test_already_queued_item_needs_no_action(self):
        # One side priced, other side KEYWORD missing + already queued
        # -> action "queued" (info only — Wednesday handles it).
        items = [_sheet_item("eggs", ww=7.90)]  # coles side missing
        rows = {"eggs": {"row_index": 5,
                         "generic_name": "Yallamundi Eggs",
                         "prices": {"woolworths": 7.90},
                         "ww_kw": "ww eggs", "coles_kw": ""}}
        queued = {"todo": [{"generic_name": "Yallamundi Eggs",
                            "keyword": "Yallamundi Eggs"}]}
        _items, entries = bc.classify_basket(items, rows, idx=None,
                                             queued=queued)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["group"], "A")
        self.assertEqual(entries[0]["action"], "queued")

    def test_substitute_fills_missing_sides_read_only(self):
        # Row exists unpriced; sibling sheet rows HAVE prices -> the
        # substitute prices are injected (source "sub") for BOTH sides
        # and the item needs no confirmation.
        items = [_sheet_item("apples")]
        rows = {"apples": {"row_index": 2,
                           "generic_name": "Royal Gala Apple 1 Kg",
                           "prices": {}, "ww_kw": "",
                           "coles_kw": "coles apples"}}
        idx = _FakeIdx([
            {"row_index": 7, "generic_name": "Royal Gala Apple 1 Kg",
             "prices": {"woolworths": 7.90}},
            {"row_index": 8, "generic_name": "Coles Royal Gala Apple 1kg",
             "prices": {"coles": 7.50}},
        ])
        items, entries = bc.classify_basket(items, rows, idx=idx)
        self.assertEqual(items[0].prices.get("woolworths"), 7.90)
        self.assertEqual(items[0].prices.get("coles"), 7.50)
        self.assertEqual(items[0].sources.get("woolworths"), "sub")
        self.assertEqual(items[0].sources.get("coles"), "sub")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "sub")
        self.assertEqual(entries[0]["sub_names"],
                         {"woolworths": "Royal Gala Apple 1 Kg",
                          "coles": "Coles Royal Gala Apple 1kg"})

    def test_partial_substitute_still_asks_for_live_fill(self):
        # Only ONE side has a sheet substitute -> item is basket-ready
        # for that side but the other still needs a live fill (group
        # recomputed from what remains: A = Coles missing).
        items = [_sheet_item("apples")]
        rows = {"apples": {"row_index": 2,
                           "generic_name": "Royal Gala Apple 1 Kg",
                           "prices": {}, "ww_kw": "",
                           "coles_kw": "coles apples"}}
        idx = _FakeIdx([
            {"row_index": 7, "generic_name": "Royal Gala Apple 1 Kg",
             "prices": {"woolworths": 7.90}},
        ])
        items, entries = bc.classify_basket(items, rows, idx=idx)
        self.assertEqual(items[0].sources.get("woolworths"), "sub")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["group"], "A")
        self.assertEqual(entries[0]["action"], "live")
        self.assertEqual(entries[0]["sub_names"],
                         {"woolworths": "Royal Gala Apple 1 Kg"})


class TestPendingState(unittest.TestCase):
    """Pending-state IO roundtrip."""

    def test_roundtrip_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = bc.OPTIMIZE_PENDING_PATH
            bc.OPTIMIZE_PENDING_PATH = Path(tmp) / "optimize_pending.json"
            try:
                self.assertIsNone(bc.load_pending())
                state = {"created_at": "t", "basket_names": ["a", "b"],
                         "items": [{"code": "KAT", "keyword": "a",
                                    "group": "A", "action": "live",
                                    "row_name": "A", "row_index": 2}]}
                bc.save_pending(state)
                loaded = bc.load_pending()
                self.assertEqual(loaded["items"][0]["code"], "KAT")
                state["items"] = []
                bc.save_pending(state)  # empty -> file removed
                self.assertIsNone(bc.load_pending())
            finally:
                bc.OPTIMIZE_PENDING_PATH = old_path


class TestExecuteConfirmations(unittest.TestCase):
    """Write semantics per group — the heart of the user rules."""

    def _gap(self, group, keyword, row_name="", add=False):
        return {"code": "KAT", "keyword": keyword, "group": group,
                "row_name": row_name, "row_index": 2 if row_name else None,
                "add": add}

    def test_a_group_writes_price_only_never_keyword_never_queues(self):
        gap = self._gap("A", "bread", row_name="Tip Top Bread 650g")
        with patch.object(bc, "search_side",
                          return_value=([_live("Coles Bakery White 650g",
                                               2.20)], "ok")), \
                patch("core.sheets_sync.set_store_keyword",
                      side_effect=AssertionError(
                          "keyword is the resolve flow's job")) as sk, \
                patch("core.sheets_sync.update_single_price",
                      return_value={"wrote": True, "row_index": 5}) as up, \
                patch("core.searched_items.add_entry",
                      side_effect=AssertionError("must not queue")) as ae:
            res = bc.execute_confirmation(gap)
        self.assertTrue(res["ok"])
        self.assertEqual(res["queued"], [])
        sk.assert_not_called()   # price-only: keyword stays empty
        up.assert_called_once()
        self.assertEqual(up.call_args.args,
                         ("Tip Top Bread 650g", "coles", 2.20))
        ae.assert_not_called()   # A/B items NEVER hit the searched list

    def test_a_group_stale_keyword_cleared_and_todo_added(self):
        # Missing side still carries a keyword (price was N/A) -> the
        # WRONG keyword is CLEARED from the sheet, the live price is
        # written, and the CORRECT product goes on the TO-DO list
        # (user rule 2026-09-03, final).
        gap = self._gap("A", "bread", row_name="Tip Top Bread 650g")
        gap["kw_present"] = ["coles"]
        with patch.object(bc, "search_side",
                          return_value=([_live("Coles Bakery White 650g",
                                               2.20)], "ok")), \
                patch("core.sheets_sync.set_store_keyword",
                      return_value={"found": True, "wrote": True}) as sk, \
                patch("core.sheets_sync.update_single_price",
                      return_value={"wrote": True, "row_index": 5}) as up, \
                patch("core.add_to_list.add_entry",
                      return_value={"added": True}) as todo, \
                patch("core.searched_items.add_entry",
                      side_effect=AssertionError("never searched list")):
            res = bc.execute_confirmation(gap)
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("todo"))
        # Keyword CLEARED (empty write), never overwritten.
        sk.assert_called_once()
        self.assertEqual(sk.call_args.args,
                         ("Tip Top Bread 650g", "coles", ""))
        up.assert_called_once()
        self.assertEqual(up.call_args.args,
                         ("Tip Top Bread 650g", "coles", 2.20))
        todo.assert_called_once()
        self.assertEqual(todo.call_args.args,
                         ("coles", "Coles Bakery White 650g",
                          "Tip Top Bread 650g"))

    def test_a_group_without_keyword_stays_price_only(self):
        # No keyword on the missing side -> price-only; the row stays
        # flagged on coles_missing until resolved (no to-do write).
        gap = self._gap("A", "bread", row_name="Tip Top Bread 650g")
        with patch.object(bc, "search_side",
                          return_value=([_live("Coles Bakery White 650g",
                                               2.20)], "ok")), \
                patch("core.sheets_sync.set_store_keyword",
                      side_effect=AssertionError) as sk, \
                patch("core.sheets_sync.update_single_price",
                      return_value={"wrote": True, "row_index": 5}) as up, \
                patch("core.add_to_list.add_entry",
                      side_effect=AssertionError) as todo:
            res = bc.execute_confirmation(gap)
        self.assertTrue(res["ok"])
        sk.assert_not_called()
        todo.assert_not_called()
        up.assert_called_once()

    def test_b_group_targets_woolworths(self):
        gap = self._gap("B", "rice", row_name="Basmati Rice 1kg")
        with patch.object(bc, "search_side",
                          return_value=([_live("WW Rice 1kg", 1.90)],
                                        "")), \
                patch("core.sheets_sync.set_store_keyword",
                      side_effect=AssertionError) as sk, \
                patch("core.sheets_sync.update_single_price",
                      return_value={"wrote": True, "row_index": 7}) as up:
            res = bc.execute_confirmation(gap)
        self.assertTrue(res["ok"])
        sk.assert_not_called()
        self.assertEqual(up.call_args.args[1], "woolworths")

    def test_coles_unavailable_fails_gracefully_and_stays_unqueued(self):
        gap = self._gap("A", "bread", row_name="Tip Top Bread 650g")
        with patch.object(bc, "search_side",
                          return_value=([], "unavailable")), \
                patch("core.sheets_sync.set_store_keyword",
                      side_effect=AssertionError) as sk:
            res = bc.execute_confirmation(gap)
        self.assertFalse(res["ok"])
        self.assertIn("unavailable", res["detail"])
        sk.assert_not_called()

    def test_c_new_compare_only_writes_nothing(self):
        gap = self._gap("C", "pasta")  # add False -> compare only
        ww = _live("Acme Pasta Penne 500g", 2.00)
        co = _live("Acme Pasta Penne 500g", 2.20)
        with patch.object(bc, "search_side",
                          side_effect=lambda store, kw, page_size=5:
                          (([ww], "") if store == "woolworths"
                           else ([co], "ok"))), \
                patch("core.sheets_sync.add_product_row",
                      side_effect=AssertionError("compare only")), \
                patch("core.searched_items.add_entry",
                      side_effect=AssertionError("compare only")):
            res = bc.execute_confirmation(gap)
        self.assertTrue(res["ok"])
        self.assertEqual(res["live"],
                         {"woolworths": {"name": "Acme Pasta Penne 500g",
                                         "price": 2.00},
                          "coles": {"name": "Acme Pasta Penne 500g",
                                    "price": 2.20}})
        self.assertIn("compared only (nothing written)", res["detail"])
        self.assertIn("$2.00", res["detail"])
        self.assertIn("$2.20", res["detail"])

    def test_c_new_add_writes_row_and_queues_both(self):
        gap = self._gap("C", "pasta", add=True)
        calls = []

        def fake_add(generic_name, store, price, **kwargs):
            calls.append((generic_name, store, kwargs))
            return {"wrote": True, "merged": False, "row_index": 42}

        def fake_queue(store, keyword, generic_name, **kwargs):
            added.append((store, keyword))
            return {"added": True, "entry": {"code": "XYZ", "store":
                    store, "keyword": keyword}}
        added = []
        ww = _live("Acme Pasta Penne 500g", 2.00)
        co = _live("Acme Pasta Penne 500g", 2.20)
        with patch.object(bc, "search_side",
                          side_effect=lambda store, kw, page_size=5:
                          (([ww], "") if store == "woolworths"
                           else ([co], "ok"))), \
                patch("core.sheets_sync.add_product_row",
                      side_effect=fake_add), \
                patch("core.add_to_list.add_entry",
                      side_effect=fake_queue):
            res = bc.execute_confirmation(gap)
        self.assertTrue(res["ok"])
        self.assertEqual(res["queued"], ["XYZ", "XYZ"])
        # One row, BOTH store prices; keyword cols empty; alias saved.
        self.assertEqual([c[1] for c in calls],
                         ["woolworths", "coles"])
        self.assertEqual(calls[0][0], calls[1][0])  # same Col A name
        for _name, _store, kwargs in calls:
            self.assertEqual(kwargs["store_keyword"], "")
            self.assertEqual(kwargs["alias"], "pasta")
        # Both store listings queued for Wednesday (website adds).
        self.assertEqual(sorted(added),
                         [("coles", "Acme Pasta Penne 500g"),
                          ("woolworths", "Acme Pasta Penne 500g")])

    def test_c_row_exists_updates_price_in_place_never_adds_or_queues(self):
        gap = self._gap("C", "beef mince",
                        row_name="Beef Mince 500g", add=True)
        with patch.object(bc, "search_side",
                          side_effect=lambda store, kw, page_size=5:
                          (([_live(f"{store} mince 500g", 5.0)], ""))), \
                patch("core.sheets_sync.set_store_keyword",
                      side_effect=AssertionError(
                          "no keywords on this row")) as sk, \
                patch("core.sheets_sync.update_single_price",
                      return_value={"wrote": True, "row_index": 3}) as up, \
                patch("core.sheets_sync.add_product_row",
                      side_effect=AssertionError("row exists")), \
                patch("core.searched_items.add_entry",
                      side_effect=AssertionError("legacy row: no queue")):
            res = bc.execute_confirmation(gap)
        self.assertTrue(res["ok"])
        sk.assert_not_called()          # no kw_present -> price-only
        self.assertEqual(up.call_count, 2)
        self.assertEqual(res["queued"], [])

    def test_c_row_stale_keyword_sides_resync(self):
        gap = self._gap("C", "beef mince",
                        row_name="Beef Mince 500g", add=True)
        gap["kw_present"] = ["woolworths", "coles"]
        with patch.object(bc, "search_side",
                          side_effect=lambda store, kw, page_size=5:
                          (([_live(f"{store} mince 500g", 5.0)], ""))), \
                patch("core.sheets_sync.set_store_keyword",
                      return_value={"found": True, "wrote": True}) as sk, \
                patch("core.sheets_sync.update_single_price",
                      return_value={"wrote": True, "row_index": 3}) as up, \
                patch("core.add_to_list.add_entry",
                      return_value={"added": True}) as todo, \
                patch("core.sheets_sync.add_product_row",
                      side_effect=AssertionError("row exists")), \
                patch("core.searched_items.add_entry",
                      side_effect=AssertionError("legacy row: no queue")):
            res = bc.execute_confirmation(gap)
        self.assertTrue(res["ok"])
        self.assertEqual(sk.call_count, 2)
        self.assertEqual(todo.call_count, 2)
        self.assertEqual(up.call_count, 2)


class TestFormatAndCli(unittest.TestCase):
    """Display blocks, info lines, live injection, CLI wiring."""

    def test_block_groups_codes_and_add_instruction(self):
        state = {"items": [
            {"code": "KAT", "keyword": "bread", "group": "A",
             "action": "live", "row_name": "Tip Top Bread 650g"},
            {"code": "ABC", "keyword": "pasta", "group": "C",
             "action": "live", "row_name": ""},
        ]}
        text = bc.format_confirmation_block(state)
        self.assertIn("LIVE SEARCH ITEMS — PLS CONFIRM", text)
        self.assertIn("A — Coles pricing missing", text)
        self.assertIn("C — No pricing at all", text)
        self.assertIn("A.1 [KAT] Tip Top Bread 650g", text)
        self.assertIn("C.1 [ABC] (not on sheet) pasta", text)
        self.assertIn("'+add'", text)
        self.assertIn("nothing written", text)

    def test_info_lines_queued_and_subs(self):
        entries = [
            {"keyword": "eggs", "action": "queued",
             "row_name": "Yallamundi Eggs"},
            {"keyword": "apples", "action": "sub",
             "sub_names": {"woolworths": "Royal Gala Apple 1 Kg"}},
        ]
        lines = bc.format_info_lines(entries)
        text = "\n".join(lines)
        self.assertIn("Already queued for Wednesday", text)
        self.assertIn("Yallamundi Eggs", text)
        self.assertIn("closest sheet substitute", text)
        self.assertIn("apples → Royal Gala Apple 1 Kg (woolworths)",
                      text)

    def test_inject_live_merges_compare_only_prices(self):
        items = [_sheet_item("rice")]
        live = {"rice": {"woolworths": {"name": "WW Rice 1kg",
                                        "price": 1.90},
                         "coles": {"name": "Coles Rice 1kg",
                                   "price": 1.80}}}
        out = bc.inject_live(items, live)
        self.assertEqual(out[0].prices,
                         {"woolworths": 1.90, "coles": 1.80})
        self.assertEqual(out[0].sources,
                         {"woolworths": "live", "coles": "live"})
        self.assertEqual(out[0].matched_names["coles"], "Coles Rice 1kg")

    def test_cli_confirm_no_pending_is_error(self):
        from grocery_price_cli import _cmd_optimize
        with patch("grocery_price_cli._load_env"), \
                patch("core.basket_confirm.load_pending",
                      return_value=None):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = _cmd_optimize(_args(confirm="all"))
        self.assertEqual(code, 1)
        self.assertIn("Nothing to confirm", err.getvalue())

    def test_cli_confirm_all_executes_and_rebuilds_plan(self):
        from grocery_price_cli import _cmd_optimize
        pending = {"created_at": "t", "basket_names": ["a", "b"],
                   "items": [{"code": "KAT", "keyword": "a",
                              "group": "A", "action": "live",
                              "row_name": "Row A", "row_index": 2,
                              "missing": ["coles"], "add": False}]}
        sheet_items = [_sheet_item("a", ww=1.0, coles=1.0),
                       _sheet_item("b", ww=1.0, coles=1.0)]
        with patch("grocery_price_cli._load_env"), \
                patch("core.basket_confirm.load_pending",
                      return_value=pending), \
                patch("core.basket_confirm.build_index",
                      return_value=None), \
                patch("core.basket_confirm.resolve_rows",
                      return_value={}), \
                patch("core.basket_confirm.classify_basket",
                      return_value=(sheet_items, [])), \
                patch("core.basket_confirm.execute_confirmation",
                      return_value={"code": "KAT", "keyword": "a",
                                    "group": "A", "ok": True,
                                    "detail": "done", "queued": [],
                                    "live": {}}) as ex, \
                patch("core.basket_confirm.save_pending") as save, \
                patch("core.price_comparator.compare_basket",
                      return_value=SimpleNamespace(
                          items=sheet_items, warnings=[],
                          not_available={},
                          team_discount_applied=False)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = _cmd_optimize(_args(confirm="KAT"))
        self.assertEqual(code, 0)
        ex.assert_called_once()
        save.assert_called_once()  # pending emptied -> file removed
        self.assertIn("SMART BASKET", out.getvalue())


def _args(**extra):
    base = dict(items="a, b", mode="auto", team_discount=None,
                min_saving=3.00, confirm=None)
    base.update(extra)
    return argparse.Namespace(**base)


class TestFindSubstituteFamilyGate(unittest.TestCase):
    """Family gate (plan S1.7): substitutes must share the item's
    sub-category — 'Chocolate Hazelnut Spread' can never answer
    'olive spread' (2026-09-07 user report)."""

    def _idx(self):
        rows = [
            {"row_index": 2, "generic_name": "Olive Oil Spread 500g",
             "prices": {},
             "subcategory": "olive spread"},
            {"row_index": 9,
             "generic_name": "Chocolate Hazelnut Spread 400g",
             "prices": {"coles": 5.75},
             "subcategory": "chocolate spread"},
            {"row_index": 11, "generic_name": "Nuttelex Spread 500g",
             "prices": {"coles": 4.20},
             "subcategory": "olive spread"},
        ]
        return _FakeIdx(rows)

    def test_no_cross_family_substitute(self):
        # No same-family priced row exists -> gate must return None,
        # never the chocolate row.
        rows = [
            {"row_index": 2, "generic_name": "Olive Oil Spread 500g",
             "prices": {}, "subcategory": "olive spread"},
            {"row_index": 9,
             "generic_name": "Chocolate Hazelnut Spread 400g",
             "prices": {"coles": 5.75},
             "subcategory": "chocolate spread"},
        ]
        sub = bc.find_substitute("olive spread", "coles", 2,
                                 _FakeIdx(rows), family="olive spread")
        self.assertIsNone(sub)

    def test_same_family_substitute_still_found(self):
        sub = bc.find_substitute("olive spread", "coles", 2,
                                 self._idx(),
                                 family="chocolate spread")
        self.assertIsNotNone(sub)
        self.assertEqual(sub["generic_name"],
                         "Chocolate Hazelnut Spread 400g")

    def test_no_family_backwards_compatible(self):
        sub = bc.find_substitute("olive spread", "coles", 2,
                                 self._idx(), family="")
        self.assertIsNotNone(sub)
        self.assertEqual(sub["generic_name"],
                         "Chocolate Hazelnut Spread 400g")


if __name__ == "__main__":
    unittest.main()
