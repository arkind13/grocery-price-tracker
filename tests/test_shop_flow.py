#!/usr/bin/env python3
"""Unit tests for core/shop_flow (plan S2.7 — Phase 2 gate).

No network, no sheet: FakeWorksheet simulates gspread; the live pair
and the sheet-write/queue functions are patched. Session file is
patched into a temp dir.
Usage:
    python -m pytest tests/test_shop_flow.py -q
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

import core.shop_flow as sf
from core.shop_flow import (
    apply_answers,
    build_questions,
    clear_session,
    is_stale,
    load_session,
    parse_answers,
    render_final_list,
    render_questions,
    save_session,
    start_run,
    undo_auto_add,
)

HEADER = [c for c in "ABCDEFGHIJKLMNOP"] + \
    ["Sub_Category", "Item_Code", "Preferred"]


def _row(name, sub="", code="", pref="", ww="", coles="",
         size="1kg", brand=""):
    r = [""] * 19
    r[0], r[2], r[3], r[4], r[6] = name, size, ww, coles, brand
    r[16], r[17], r[18] = sub, code, pref
    return r


ROWS = [
    _row("Full Cream Milk 3L", "milk", "JQN", "P", ww="4.90"),
    _row("Lite Milk 2L", "milk", "LTM"),
    _row("RAW SUGAR 2KG", "sugar", "KYQ", coles="3.00"),
    _row("Raw Sugar 3Kg", "sugar", "ZAJ"),
    _row("Yallamundi Eggs", "eggs", "PAK"),
    _row("Eggs Free Rage 12Pc", "eggs", "BXW"),
    _row("Olive Oil Spread 500g", "olive spread", "OOS"),
]


class FakeWorksheet:
    """Mock gspread Worksheet (test_preferences pattern)."""

    def __init__(self, rows=None):
        self._values = [list(HEADER)] + [list(r) for r in (
            rows if rows is not None else ROWS)]
        self.updates = []
        self.deleted_rows = []
        self.reads = 0

    def get_all_values(self):
        self.reads += 1
        return [list(r) for r in self._values]

    def update(self, *args, **kwargs):
        self.updates.append((args, kwargs))
        return None

    def delete_rows(self, index):
        self.deleted_rows.append(index)
        if 1 <= index <= len(self._values):
            del self._values[index - 1]
        return None


def _live_result(name, price, store="woolworths", size="500g"):
    return SimpleNamespace(raw_name=name, price=price, store=store,
                           size=size, brand="TestBrand",
                           category="",
                           is_special=False, special_desc="")


def _patched_session():
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "shop_session.json"
    patches = [
        mock.patch.object(sf, "SESSION_PATH", path),
        mock.patch("core.add_to_list.ADD_TO_LIST_PATH",
                   Path(tmp.name) / "add_to_list.json"),
    ]
    return tmp, patches


class TestStartRun(unittest.TestCase):
    def test_start_run_category_with_p_prices(self):
        ws = FakeWorksheet()
        sess = start_run(ws, ["milk"])
        it = sess["items"][0]
        self.assertEqual(it["stage"], "priced")
        self.assertEqual(it["resolved_name"], "Full Cream Milk 3L")
        self.assertEqual(ws.reads, 1)

    def test_start_run_category_no_p_asks_pick(self):
        ws = FakeWorksheet()
        sess = start_run(ws, ["sugar"])
        it = sess["items"][0]
        self.assertEqual(it["stage"], "ask_pick")
        self.assertEqual(len(it["options"]), 2)

    def test_start_run_qualified_phrase_hits_category(self):
        for phrase in ("Sugar-2 kg", "sugar 2kg", "woolworths sugar"):
            ws = FakeWorksheet()
            sess = start_run(ws, [phrase])
            self.assertEqual(sess["items"][0]["subcategory"],
                             "sugar", phrase)
            self.assertIn(sess["items"][0]["stage"],
                          ("priced", "ask_pick"))

    def test_start_run_product_exact_name(self):
        ws = FakeWorksheet()
        sess = start_run(ws, ["Full Cream Milk 3L"])
        it = sess["items"][0]
        self.assertEqual(it["stage"], "priced")
        self.assertEqual(it["row_index"], 2)

    def test_start_run_untracked_asks_live(self):
        ws = FakeWorksheet()
        sess = start_run(ws, ["lindt powder"])
        self.assertEqual(sess["items"][0]["stage"], "ask_live")


class TestQuestionsAndAnswers(unittest.TestCase):
    def test_questions_one_message_all_kinds(self):
        ws = FakeWorksheet()
        sess = start_run(ws, ["sugar", "lindt powder"])
        qs = build_questions(sess)
        self.assertEqual([q["kind"] for q in qs],
                         ["pick", "live"])
        text = render_questions(qs)
        self.assertTrue(text.startswith("🛒 SHOPPING LIST — "
                                        "2 question(s)"))
        self.assertIn("1. sugar — preferred?", text)
        self.assertIn("2. lindt powder — not tracked. "
                      "Live search now? (y/n)", text)
        self.assertIn("Reply like: 1=1, 2=y", text)

    def test_parse_answers_grammar(self):
        got = parse_answers("1=2; 2=woolworths; 3=y; 4=skip\n5=Macro "
                            "Organic Eggs")
        self.assertEqual(got, {1: "2", 2: "woolworths", 3: "y",
                               4: "skip", 5: "Macro Organic Eggs"})

    def test_parse_answers_invalid_qid_ignored(self):
        self.assertEqual(parse_answers("x=1; 2=; =y; 3= y "),
                         {3: "y"})

    def test_apply_pick_number_sets_preferred(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["sugar"])
            with mock.patch("core.preferences.set_preferred",
                            return_value={"wrote": True}) as sp:
                sess, log = apply_answers(ws, sess, {1: "2"})
            sp.assert_called_once()
            self.assertEqual(sess["items"][0]["stage"], "priced")
            self.assertEqual(sess["items"][0]["resolved_name"],
                             "Raw Sugar 3Kg")

    def test_apply_pick_free_text_opens_store_question(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["sugar"])
            sess, _log = apply_answers(ws, sess, {1: "Macro Organic "
                                                       "Sugar"})
            it = sess["items"][0]
            self.assertEqual(it["stage"], "ask_store")
            self.assertEqual(it["user_name"], "Macro Organic Sugar")
            qs = build_questions(sess)
            self.assertEqual(qs[0]["kind"], "store")
            self.assertIn("woolworths or coles?",
                          render_questions(qs))

    def test_apply_store_runs_handshake_price_and_todo_no_keyword(
            self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["sugar"])
            sess, _ = apply_answers(ws, sess, {1: "Coles Raw Sugar "
                                                    "2kg"})
            it = sess["items"][0]
            self.assertEqual(it["stage"], "ask_store")
            with mock.patch.object(
                    sf, "_live_pair",
                    return_value=([_live_result("Coles Raw Sugar "
                                                "2kg", 3.0,
                                                store="coles")],
                                  [], "ok")), \
                mock.patch("core.sheets_sync.add_product_row",
                           return_value={"row_index": 4,
                                         "merged": False}) as apr, \
                mock.patch("core.add_to_list.add_entry",
                           return_value={"added": True, "entry": {
                               "code": "KAT", "store": "coles",
                               "keyword": "Coles Raw Sugar 2kg",
                               "generic_name": "Coles Raw Sugar "
                                               "2kg"}}) as ae:
                sess, log = apply_answers(ws, sess,
                                          {it["question_id"]:
                                           "coles"})
            apr.assert_called_once()
            kwargs = apr.call_args.kwargs
            self.assertEqual(kwargs.get("store_keyword"), "")
            self.assertEqual(kwargs.get("store"), "coles")
            ae.assert_called_once()
            self.assertEqual(sess["items"][0]["stage"], "priced")
            self.assertEqual(sess["items"][0]["auto_add"]["code"],
                             "KAT")
            self.assertTrue(any("KAT" in ln for ln in log))

    def test_apply_live_yes_auto_adds_top_result(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["lindt powder"])
            qid = sess["items"][0]["question_id"]
            with mock.patch.object(
                    sf, "_live_pair",
                    return_value=([_live_result("Lindt Hot Choc "
                                                "Flakes 210g", 12.0)],
                                  [], "ok")), \
                mock.patch("core.sheets_sync.add_product_row",
                           return_value={"row_index": 9,
                                         "merged": False}) as apr, \
                mock.patch("core.add_to_list.add_entry",
                           return_value={"added": True, "entry": {
                               "code": "LHT"}}):
                sess, log = apply_answers(ws, sess, {qid: "y"})
            self.assertEqual(sess["items"][0]["stage"], "priced")
            self.assertEqual(sess["items"][0]["auto_add"]["code"],
                             "LHT")
            kwargs = apr.call_args.kwargs
            self.assertEqual(kwargs.get("store_keyword"), "")
            self.assertTrue(any("wrong LHT" in ln for ln in log))

    def test_apply_live_no_skips(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["lindt powder"])
            qid = sess["items"][0]["question_id"]
            sess, log = apply_answers(ws, sess, {qid: "n"})
            self.assertEqual(sess["items"][0]["stage"], "skipped")
            self.assertTrue(any("skipped" in ln for ln in log))

    def test_handshake_not_found_reasks_with_note(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["sugar"])
            sess, _ = apply_answers(ws, sess, {1: "Unobtainium "
                                                    "Sugar"})
            it = sess["items"][0]
            with mock.patch.object(sf, "_live_pair",
                                   return_value=([], [],
                                                 "unavailable")):
                sess, log = apply_answers(
                    ws, sess, {it["question_id"]: "coles"})
            self.assertEqual(it["stage"], "ask_store")
            self.assertIn("not found", it.get("note", ""))
            qs = build_questions(sess)
            self.assertEqual(qs[0]["kind"], "store")
            self.assertIn("not found live at coles",
                          render_questions(qs))

    def test_label_answer_review_marks_needs_review(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["Full Cream Milk 3L"])
            it = sess["items"][0]
            it["stage"] = "ask_label"
            it["subcategory"] = "milk"
            sess, _ = apply_answers(ws, sess,
                                    {it["question_id"]: "review"})
            self.assertEqual(sess["items"][0]["subcategory"],
                             "needs review")


class TestPartialAndFinal(unittest.TestCase):
    def test_partial_answers_reask_remaining(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["sugar", "lindt powder"])
            pick_qid = sess["items"][0]["question_id"]
            live_qid = sess["items"][1]["question_id"]
            with mock.patch("core.preferences.set_preferred",
                            return_value={"wrote": True}):
                sess, _ = apply_answers(ws, sess, {pick_qid: "1"})
            qs = build_questions(sess)
            self.assertEqual([x["qid"] for x in qs], [live_qid])
            self.assertEqual(qs[0]["kind"], "live")

    def test_final_list_template_exact(self):
        ws = FakeWorksheet(rows=[
            _row("Full Cream Milk 3L", "milk", "JQN", "P",
                 coles="5.15", size="3L"),
        ])
        sess = {"run_id": datetime.now(timezone.utc)
                .isoformat(timespec="seconds"),
                "next_qid": 2,
                "items": [{"raw": "milk", "stage": "priced",
                           "subcategory": "milk",
                           "resolved_name": "Full Cream Milk 3L",
                           "row_index": 2, "user_name": "",
                           "store": "", "question_id": None,
                           "options": [], "live_done": False,
                           "auto_add": None}]}
        got = render_final_list(ws, sess)
        self.assertEqual(
            got,
            "🛒 YOUR SHOPPING LIST (1 item(s))\n"
            "1. Full Cream Milk 3L · 3L · 🟢 — · 🔴 $5.15\n"
            "📊 WW total $0.00 · Coles total $5.15\n"
            "📋 To-do (add on website): none")


class TestUndoAndStaleness(unittest.TestCase):
    def test_undo_created_row_removes_row_and_todo(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["lindt powder"])
            it = sess["items"][0]
            it["stage"] = "priced"
            it["auto_add"] = {"code": "LHT", "row_index": 9,
                              "created_row": True,
                              "prev_price": ""}
            save_session(sess)
            with mock.patch("core.add_to_list.remove_by_code",
                            return_value={"removed": [{}]}) as rm:
                res = undo_auto_add(ws, "LHT")
            self.assertTrue(res["undone"])
            self.assertEqual(ws.deleted_rows, [9])
            rm.assert_called_once_with("LHT")
            reloaded = load_session()
            self.assertEqual(reloaded["items"][0]["stage"],
                             "ask_live")

    def test_undo_merged_row_restores_price(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            ws = FakeWorksheet()
            sess = start_run(ws, ["sugar"])
            it = sess["items"][0]
            it["stage"] = "priced"
            it["store"] = "coles"
            it["auto_add"] = {"code": "KYQ", "row_index": 4,
                              "created_row": False,
                              "prev_price": "3.00"}
            save_session(sess)
            with mock.patch("core.add_to_list.remove_by_code",
                            return_value={"removed": [{}]}):
                res = undo_auto_add(ws, "KYQ")
            self.assertTrue(res["undone"])
            self.assertEqual(len(ws.updates), 1)
            _args, kwargs = ws.updates[0]
            self.assertEqual(kwargs.get("range_name"), "E4")
            self.assertEqual(kwargs.get("values"), [["3.00"]])

    def test_session_stale_24h_cleared(self):
        tmp, patches = _patched_session()
        with tmp, patches[0], patches[1]:
            old = {"run_id": (datetime.now(timezone.utc)
                              - timedelta(hours=25))
                   .isoformat(timespec="seconds"),
                   "items": [], "next_qid": 1}
            save_session(old)
            self.assertTrue(is_stale(old))
            self.assertIsNone(load_session())
            clear_session()
            self.assertIsNone(load_session())

    def test_read_budget_one_read_per_invocation(self):
        ws = FakeWorksheet()
        start_run(ws, ["milk", "sugar"])
        self.assertLessEqual(ws.reads, 2)
        # render_final_list: exactly one read
        ws2 = FakeWorksheet()
        render_final_list(ws2, {"run_id": "2026-09-07T00:00:00+00:00",
                                "items": [], "next_qid": 1})
        self.assertEqual(ws2.reads, 1)


if __name__ == "__main__":
    unittest.main()
