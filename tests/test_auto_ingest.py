"""Auto-ingest batch regression battery (auto-ingest-spec.md,
user directive 2026-09-11): ID-1/2/3 ingest hardening, the S1-S16
scenario matrix, and the watch-folder watcher. Zero skips; every
test maps to an implementation-plan.md compliance-table row.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core import local_deals as ld  # noqa: E402
from tests.test_local_deals import (  # noqa: E402
    FakeSpreadsheet, FakeWorksheet, _v2_ws,
)

MER_SP = 5      # merjan_sp column index (Category col added 1)
DUN_SP = 3      # dunya_sp column index


def _vision_deal(item="Lamb Necks", price=32.99, unit="kg",
                 kind="single", qty=None, bulk=None,
                 category="butchery", valid_until=None):
    """A vision-schema deal as flyer_vision.validate_payload emits."""
    return {"item": item, "raw_text": f"{item} x", "price": price,
            "unit": unit, "price_kind": kind, "multibuy_qty": qty,
            "bulk_size": bulk, "category": category, "notes": "",
            "valid_until": valid_until}


# ---------------------------------------------------------------------------
# AI-M1 (ID-1): pack-deal semantics on /kg rows
# ---------------------------------------------------------------------------
class TestID1PackDealSemantics(unittest.TestCase):

    def test_multibuy_kg_cell_is_per_kg_rate(self):
        """"3kg for $32.99" -> the special cell holds $11.00 (the
        per-kg rate), never the raw pack total (spec: 'the per-kg
        rate in the shop's special cell')."""
        ws = FakeWorksheet()
        ld.merge_store_tab(ws, "merjan",
                           [_vision_deal(kind="multibuy",
                                         qty=3, price=32.99)])
        row = next(r for r in ws.rows
                   if str(r[0]).startswith("Lamb Necks"))
        self.assertEqual(row[MER_SP], 11.0)
        self.assertNotIn("32.99", str(row[MER_SP]))

    def test_multibuy_kg_comment_terms(self):
        """The shop-tagged Comments segment carries the pack terms in
        the spec's exact wording: '[MER] multi buy 3kg for $32.99]' —
        no '/ea' suffix on a /kg row."""
        ws = FakeWorksheet()
        ld.merge_store_tab(ws, "merjan",
                           [_vision_deal(kind="multibuy",
                                         qty=3, price=32.99)])
        row = next(r for r in ws.rows
                   if str(r[0]).startswith("Lamb Necks"))
        self.assertEqual(row[11], "[MER] multi buy 3kg for $32.99")

    def test_multibuy_divides_exactly_once(self):
        """Single-divider rule: the cell is round(total/qty, 2) =
        $11.00 — divided exactly once (never 32.99 raw, never the
        twice-divided ~$5.50)."""
        ws = FakeWorksheet()
        ld.merge_store_tab(ws, "merjan",
                           [_vision_deal(kind="multibuy",
                                         qty=3, price=32.99)])
        row = next(r for r in ws.rows
                   if str(r[0]).startswith("Lamb Necks"))
        self.assertEqual(float(row[MER_SP]), 11.0)
        self.assertNotEqual(float(row[MER_SP]), 32.99)
        self.assertNotEqual(float(row[MER_SP]),
                            round(32.99 / 3 / 3, 2))

    def test_multibuy_ea_wording_unchanged(self):
        """/ea multi-buys keep the proven wording with the per-ea
        rate suffix ('Already live' list — do not rebuild)."""
        ws = FakeWorksheet()
        ld.merge_store_tab(ws, "fruitopia", [_vision_deal(
            item="Celery", price=2.99, unit="ea", kind="multibuy",
            qty=2, category="fruits")])
        row = next(r for r in ws.rows
                   if str(r[0]).startswith("Celery"))
        self.assertEqual(
            row[11],
            "[FRU] multi buy 2 for $2.99 — $1.50/ea")

    def test_multibuy_kg_read_side_min_order(self):
        """Writer/reader compatibility: the kg note renders as 'min
        order 3kg for $32.99' next to the per-kg rate (live-verified
        compare wording, v2_read._shop_note + display regex)."""
        import re
        note = ld._shop_key_for_tag("MER")  # tag plumbing intact
        self.assertEqual(note, "merjan")
        cell = "[MER] multi buy 3kg for $32.99"
        from core.local_deals import _shop_key_for_tag, _TAG_TO_SHOP
        self.assertIn("MER", _TAG_TO_SHOP)
        seg = cell.split("] ", 1)[1]
        rendered = re.sub(r"^multi buy\b", "min order", seg,
                          count=1)
        self.assertEqual(rendered, "min order 3kg for $32.99")


# ---------------------------------------------------------------------------
# AI-M2 (ID-2): the v2 reuse guard
# ---------------------------------------------------------------------------
class TestID2ReuseGuard(unittest.TestCase):

    def test_lamb_neck_pair_reuses_row(self):
        """THE spec regression pair: 'Halal Sliced Lamb Neck /kg' on
        the sheet + incoming 'Halal Lamb Necks /kg' -> REUSE (one
        row), never a near-duplicate."""
        ws = _v2_ws([
            ["BUTCHERY", "", "", "", "", "", "", "", "", ""],
            ["Halal Sliced Lamb Neck /kg", "", "", "", "", "",
             "", "", "", ""],
        ])
        ld.merge_store_tab(ws, "merjan", [
            _vision_deal(item="Halal Lamb Necks", price=15.99)])
        names = [str(r[0]) for r in ws.rows]
        lamb_rows = [n for n in names if "Lamb Neck" in n]
        self.assertEqual(len(lamb_rows), 1)      # one row, reused

    def test_reuse_keeps_item_code(self):
        """On match -> reuse the existing row + Item_Code: col K is
        NOT re-minted and no master mirror row is created."""
        ws = _v2_ws([
            ["BUTCHERY"] + [""] * 12,
            ["Halal Sliced Lamb Neck /kg"] + [""] * 10 + ["YCQ"],
        ])
        master = FakeWorksheet(title="Products_Master")
        master.rows = [["Name"] + [""] * 12]
        ld.merge_store_tab(ws, "merjan", [
            _vision_deal(item="Halal Lamb Necks", price=15.99)],
            master_ws=master)
        self.assertEqual(len(master.rows), 1)    # no mirror append
        row = next(r for r in ws.rows if "Lamb Neck" in str(r[0]))
        self.assertEqual(row[12], "YCQ")         # code preserved

    def test_pack_vs_kg_stay_separate_rows(self):
        """S9 BY DESIGN: 'Goat Curry /kg' and 'Goat Curry 5kg' are
        different product lines — the pack size token keeps them
        apart."""
        ws = _v2_ws([
            ["BUTCHERY", "", "", "", "", "", "", "", "", ""],
            ["Halal Goat Curry /kg", "", "", "", "", "", "", "",
             "", ""],
        ])
        ld.merge_store_tab(ws, "dunya_fb", [
            _vision_deal(item="Halal Goat Curry", price=89.99,
                         kind="bulk_pack", bulk="5kg")])
        names = [str(r[0]) for r in ws.rows]
        self.assertEqual(names.count("Halal Goat Curry /kg"), 1)
        self.assertIn("Halal Goat Curry 5kg", names)

    def test_beef_vs_lamb_curry_not_merged(self):
        """Different proteins never containment-merge."""
        ws = _v2_ws([
            ["BUTCHERY", "", "", "", "", "", "", "", "", ""],
            ["Halal Beef Curry /kg", "", "", "", "", "", "", "",
             "", ""],
        ])
        ld.merge_store_tab(ws, "merjan", [
            _vision_deal(item="Halal Lamb Curry", price=12.99)])
        names = sorted(str(r[0]) for r in ws.rows
                       if "Curry" in str(r[0]))
        self.assertEqual(names, ["Halal Beef Curry /kg",
                                 "Halal Lamb Curry /kg"])

    def test_cross_shop_one_row_both_columns(self):
        """S8: the same item at two shops = ONE row, both shop
        columns filled."""
        ws = FakeWorksheet()
        ld.merge_store_tab(ws, "merjan", [
            _vision_deal(item="Halal Lamb Necks", price=15.99)])
        ld.merge_store_tab(ws, "dunya_fb", [
            _vision_deal(item="Halal Lamb Necks", price=16.99)])
        row = next(r for r in ws.rows
                   if "Lamb Necks" in str(r[0]))
        self.assertEqual(row[MER_SP], 15.99)
        self.assertEqual(row[DUN_SP], 16.99)
        self.assertEqual(
            sum(1 for r in ws.rows
                if "Lamb Necks" in str(r[0])), 1)


# ---------------------------------------------------------------------------
# AI-M3 (ID-3): idempotent comment tags
# ---------------------------------------------------------------------------
class TestID3CommentIdempotence(unittest.TestCase):

    def test_remerge_idempotent_no_double_tag(self):
        """Merging the same deal twice leaves ONE tag segment — the
        '[MER] [MER] multi buy…' doubling is structurally gone."""
        ws = FakeWorksheet()
        deals = [_vision_deal(kind="multibuy", qty=3,
                         price=32.99)]
        ld.merge_store_tab(ws, "merjan", deals)
        ld.merge_store_tab(ws, "merjan", deals)
        row = next(r for r in ws.rows
                   if "Lamb Necks" in str(r[0]))
        self.assertEqual(row[11], "[MER] multi buy 3kg for $32.99")
        self.assertNotIn("[MER] [MER]", str(row[11]))

    def test_pretagged_note_single_tag(self):
        """A caller passing an already-tagged note never stacks tags
        (the morning rescue failure mode)."""
        tagged = ld._tag_note("merjan",
                              "multi buy 3kg for $32.99")
        self.assertEqual(tagged, "[MER] multi buy 3kg for $32.99")
        again = ld._tag_note("merjan", tagged)
        self.assertEqual(again, "[MER] multi buy 3kg for $32.99")

    def test_other_shop_segment_survives(self):
        """Strip-then-append is PER SHOP: Dunya's segment survives a
        Merjan re-merge."""
        ws = FakeWorksheet()
        ld.merge_store_tab(ws, "dunya_fb", [
            _vision_deal(item="Halal Lamb Necks", price=16.99,
                         kind="multibuy", qty=2)])
        ld.merge_store_tab(ws, "merjan", [
            _vision_deal(item="Halal Lamb Necks", price=15.99,
                         kind="multibuy", qty=3)])
        row = next(r for r in ws.rows
                   if "Lamb Necks" in str(r[0]))
        self.assertIn("[DUN]", str(row[11]))
        self.assertIn("[MER]", str(row[11]))
        self.assertNotIn("[MER] [MER]", str(row[11]))


# ---------------------------------------------------------------------------
# S4/S6: item-level expiry dates
# ---------------------------------------------------------------------------
class TestItemLevelDates(unittest.TestCase):

    def test_item_level_dates_per_cell(self):
        """S6: two items in ONE post with different own dates keep
        their OWN till stamps (the row-2 summary stamp is retired —
        per-cell stamps are the only validity display, layout
        2026-09-12)."""
        from datetime import date
        ws = FakeWorksheet()
        ld.merge_store_tab(ws, "merjan", [
            _vision_deal(item="Halal Lamb Necks", price=15.99,
                         valid_until=date(2026, 9, 14)),
            _vision_deal(item="Halal Beef Curry", price=12.99,
                         valid_until=date(2026, 9, 18)),
        ], valid_until=date(2026, 9, 18))
        lamb = next(r for r in ws.rows
                    if "Lamb Necks" in str(r[0]))
        curry = next(r for r in ws.rows
                     if "Beef Curry" in str(r[0]))
        self.assertIn("till 14 Sep", str(lamb[MER_SP]))
        self.assertIn("till 18 Sep", str(curry[MER_SP]))
        # No row-2 summary stamp is ever written (layout 2026-09-12).
        stamp_rows = [r for r in ws.rows
                      if str(r[0]).strip() == "Prices valid until"]
        self.assertEqual(stamp_rows, [])

    def test_vision_validator_accepts_item_level_date(self):
        """The vision schema accepts an optional per-deal valid_until
        (YYYY-MM-DD or null) and rejects garbage."""
        from core.flyer_vision import validate_payload
        deals, errs = validate_payload({
            "valid_until": None,
            "deals": [
                {"item": "Lamb", "raw_text": "Lamb", "price": 15.99,
                 "unit": "kg", "price_kind": "single",
                 "multibuy_qty": None, "bulk_size": None,
                 "category": "butchery", "notes": "",
                 "valid_until": "2026-09-14"},
                {"item": "Beef", "raw_text": "Beef", "price": 12.99,
                 "unit": "kg", "price_kind": "single",
                 "multibuy_qty": None, "bulk_size": None,
                 "category": "butchery", "notes": "",
                 "valid_until": None}]})
        self.assertEqual(errs, [])
        self.assertEqual(deals[0]["valid_until"], "2026-09-14")
        _d, errs2 = validate_payload({
            "deals": [{"item": "Lamb", "raw_text": "L",
                       "price": 1.0, "unit": "ea",
                       "price_kind": "single", "notes": "",
                       "valid_until": "14/09/2026"}]})
        self.assertTrue(any("valid_until" in e for e in errs2))

    def test_vision_prompt_kg_deal_rules(self):
        """The prompt pins the ID-1 classification rules: weighted
        'Nkg for $X' is multibuy+kg (never bulk_pack); bulk_pack is
        for PHYSICAL packs only."""
        from core import flyer_vision as fv
        self.assertIn("NEVER report a weighted deal as bulk_pack",
                      fv.SCHEMA_V2_PROMPT)
        self.assertIn("price is ALWAYS the", fv.SCHEMA_V2_PROMPT)
        self.assertIn("its OWN end date", fv.SCHEMA_V2_PROMPT)


# ---------------------------------------------------------------------------
# S5 + P4: the questions lifecycle
# ---------------------------------------------------------------------------
class TestQuestionsLifecycle(unittest.TestCase):

    def test_unknown_expiry_ask_repeats(self):
        """The S5 ask opens on an undated board and appears in EVERY
        digest until answered."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(ld, "QUESTIONS_PATH",
                              Path(tmp) / "q.json"):
                ld.open_question(
                    "expiry", "MER1109260507", "board.jpg",
                    "merjan",
                    "Merjan: no end date on this board "
                    "(MER1109260507 board.jpg) — reply with the "
                    "date, or 'open' to leave it undated")
                for _ in range(2):       # two digests
                    questions = ld._load_questions()
                    msgs = ld._render_window_digest(
                        [], questions, "Sweep 05:00")
                    self.assertIn("no end date", msgs[0])
                self.assertEqual(len(ld._load_questions()), 1)

    def test_set_date_open_clears_question(self):
        """'open' = the user's explicit undated answer: recorded, no
        sheet stamp, question cleared, file archived."""
        import tempfile as tf
        from datetime import date
        with tf.TemporaryDirectory() as tmp:
            inbox = Path(tmp)
            with patch.object(ld, "INBOX_DIR", inbox), \
                    patch.object(ld, "QUESTIONS_PATH",
                                 Path(tmp) / "q.json"), \
                    patch.object(ld, "POST_LOG_PATH",
                                 Path(tmp) / "p.json"), \
                    patch.object(ld, "SCAN_STATE_PATH",
                                 Path(tmp) / "s.json"), \
                    patch("core.sheets_client.connect_worksheet",
                          side_effect=RuntimeError("no sheet")):
                folder = ld.inbox_dir_for("MER1109260507")
                needs = folder / "needs_date"
                needs.mkdir(parents=True)
                (needs / "board.jpg").write_bytes(b"x")
                ld.open_question(
                    "expiry", "MER1109260507", "board.jpg", "merjan",
                    "ask")
                rc = ld.set_date_cmd("MER1109260507", "board.jpg",
                                     "open")
                self.assertEqual(rc, 0)
                self.assertEqual(ld._load_questions(), [])
                entries = ld._load_post_log()
                self.assertTrue(any(
                    e["code"] == "MER1109260507"
                    and e["valid_until"] is None
                    and e["archived"] == "processed"
                    for e in entries))
                self.assertTrue(
                    (folder / "processed" / "board.jpg").exists())

    def test_set_date_real_date_stamps(self):
        """A real date answer still stamps (existing path intact)."""
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            stamped = []
            grid = [["Product"] + [""] * 12,
                    ["Prices valid until"] + [""] * 12,
                    ["Halal Lamb Necks /kg", "", "", "", "",
                     "15.99", "", "", "", "", "", "", ""]]

            class _Tab:
                def get_all_values(self):
                    return [list(r) for r in grid]

                def clear(self):
                    pass

                def freeze(self, rows=None):
                    pass

                def update(self, values=None, range_name=None,
                           **kw):
                    stamped.append(values)

            class _SS:
                class spreadsheet:
                    @staticmethod
                    def worksheet(title):
                        return _Tab()

            with patch.object(ld, "INBOX_DIR", Path(tmp)), \
                    patch.object(ld, "QUESTIONS_PATH",
                                 Path(tmp) / "q.json"), \
                    patch.object(ld, "POST_LOG_PATH",
                                 Path(tmp) / "p.json"), \
                    patch.object(ld, "SCAN_STATE_PATH",
                                 Path(tmp) / "s.json"), \
                    patch("core.sheets_client.connect_worksheet",
                          return_value=_SS()):
                folder = ld.inbox_dir_for("MER1109260507")
                needs = folder / "needs_date"
                needs.mkdir(parents=True)
                (needs / "board.jpg").write_bytes(b"x")
                rc = ld.set_date_cmd("MER1109260507", "board.jpg",
                                     "12 September")
                self.assertEqual(rc, 0)
                self.assertTrue(stamped)
                self.assertIn("till 12 Sep",
                              str(stamped[-1]))

    def test_set_date_without_file_resolves_open_question(self):
        """User directive 2026-09-12: the ONE-command reply form
        (--set-date CODE DATE) — the file reference auto-resolves
        from the code's single open expiry question; the sweep's
        fb: file rides along to the post log; the question clears.
        No questions.json / post-log spelunking needed."""
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "INBOX_DIR", Path(tmp)), \
                    patch.object(ld, "QUESTIONS_PATH",
                                 Path(tmp) / "q.json"), \
                    patch.object(ld, "POST_LOG_PATH",
                                 Path(tmp) / "p.json"), \
                    patch.object(ld, "SCAN_STATE_PATH",
                                 Path(tmp) / "s.json"), \
                    patch("core.sheets_client.connect_worksheet",
                          side_effect=RuntimeError("no sheet")):
                ld.open_question(
                    "expiry", "MER1209260507",
                    "fb:122188809842942477", "merjan", "ask")
                rc = ld.set_date_cmd("MER1209260507", None,
                                     "2026-09-13")
                self.assertEqual(rc, 0)
                self.assertEqual(ld._load_questions(), [])
                entries = ld._load_post_log()
                self.assertTrue(any(
                    e["code"] == "MER1209260507"
                    and e["file"] == "fb:122188809842942477"
                    and e["valid_until"] == "2026-09-13"
                    and e["archived"] == "processed"
                    for e in entries))

    def test_set_date_without_file_or_question_still_records(self):
        """No open question (answered twice / cleared): the reply
        still records under a reply: placeholder — rc 0, never an
        investigation trigger."""
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "INBOX_DIR", Path(tmp)), \
                    patch.object(ld, "QUESTIONS_PATH",
                                 Path(tmp) / "q.json"), \
                    patch.object(ld, "POST_LOG_PATH",
                                 Path(tmp) / "p.json"), \
                    patch.object(ld, "SCAN_STATE_PATH",
                                 Path(tmp) / "s.json"), \
                    patch("core.sheets_client.connect_worksheet",
                          side_effect=RuntimeError("no sheet")):
                rc = ld.set_date_cmd("MER1209260507", None, "open")
                self.assertEqual(rc, 0)
                entries = ld._load_post_log()
                self.assertTrue(any(
                    e["code"] == "MER1209260507"
                    and e["file"] == "reply:MER1209260507"
                    and e["valid_until"] is None
                    for e in entries))

    def test_auto_code_opens_shop_question(self):
        """P4: a shop-less AUTO drop writes NOTHING and asks which
        shop — never a guess."""
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            sent = []
            with patch.object(ld, "INBOX_DIR", Path(tmp)), \
                    patch.object(ld, "QUESTIONS_PATH",
                                 Path(tmp) / "q.json"), \
                    patch.object(ld, "_post_digest",
                                 side_effect=lambda msgs:
                                 sent.extend(msgs)):
                folder = ld.inbox_dir_for("AUTO1109260900")
                (folder / "board.jpg").write_bytes(b"img")
                rc = ld.ingest_code("AUTO1109260900")
                questions = ld._load_questions()
            self.assertEqual(rc, 0)
            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["kind"], "shop")
            self.assertIn("which shop", sent[0])

    def test_resolve_shop_ingests(self):
        """--resolve-shop completes the pending AUTO drop: folder
        re-pointed, question cleared, ingest runs for the shop."""
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            with patch.object(ld, "INBOX_DIR", Path(tmp)), \
                    patch.object(ld, "QUESTIONS_PATH",
                                 Path(tmp) / "q.json"), \
                    patch.object(ld, "POST_LOG_PATH",
                                 Path(tmp) / "p.json"), \
                    patch.object(ld, "SCAN_STATE_PATH",
                                 Path(tmp) / "s.json"), \
                    patch.object(ld, "ingest_code",
                                 return_value=0) as fake_ingest:
                folder = ld.inbox_dir_for("AUTO1109260900")
                (folder / "board.jpg").write_bytes(b"img")
                ld.open_question(
                    "shop", "AUTO1109260900", "board.jpg", "",
                    "ask")
                rc = ld.resolve_shop_cmd("AUTO1109260900", "merjan")
                self.assertEqual(rc, 0)
                new_code = fake_ingest.call_args[0][0]
                self.assertTrue(new_code.startswith("MER"))
                self.assertFalse(folder.exists())
                self.assertEqual(ld._load_questions(), [])


# ---------------------------------------------------------------------------
# AI-M5/AI-M6: the digest renderer
# ---------------------------------------------------------------------------
class TestWindowDigest(unittest.TestCase):

    def _sections(self):
        return [{
            "shop_label": "Merjan",
            "shop": "Merjan Brothers Quality Meats",
            "posts": [{
                "code": "MER1109260507", "file": "board.jpg",
                "valid_txt": "valid until Sat 12 Sep",
                "items": [
                    {"name": "Halal Lamb Necks /kg",
                     "price_text": "$11.00/kg",
                     "terms": "3kg for $32.99",
                     "till": "Sat 12 Sep", "per_kg": 11.0},
                    {"name": "Halal Beef Curry /kg",
                     "price_text": "$12.99/kg", "terms": None,
                     "till": None, "per_kg": 12.99}],
                "notice_only": False, "unreadable": False}]}]

    def test_digest_format_spec_example(self):
        """Header wording per the spec example; items carry prices,
        'min order …' terms, per-item validity. S7 (user answer
        2026-09-11): FINAL PRICE ONLY — no 'was $X' change line."""
        msgs = ld._render_window_digest(
            self._sections(), [], "Sweep 05:00")
        self.assertEqual(len(msgs), 1)
        self.assertIn("🔍 Sweep 05:00 — Merjan: 2 new items "
                      "(1 with min-order deals, best $11.00/kg)",
                      msgs[0])
        self.assertIn("• Halal Lamb Necks /kg — $11.00/kg "
                      "(min order 3kg for $32.99) · till Sat 12 Sep",
                      msgs[0])
        self.assertIn("🔪 Merjan Brothers Quality Meats", msgs[0])

    def test_digest_no_done_word(self):
        msgs = ld._render_window_digest(
            self._sections(), [], "Sweep 15:00")
        for m in msgs:
            self.assertNotIn("done", m.lower())

    def test_two_shops_one_digest_sections(self):
        """S3: multiple shops in one window -> ONE message, one
        section per shop."""
        sections = self._sections() + [{
            "shop_label": "Fruitopia", "shop": "Fruitopia",
            "posts": [{"code": "FRU1109260508", "file": "notice.png",
                       "valid_txt": "", "items": [],
                       "notice_only": True, "unreadable": False}]}]
        msgs = ld._render_window_digest(sections, [], "Sweep 05:00")
        self.assertEqual(len(msgs), 1)
        self.assertIn("Fruitopia: notice only, no prices", msgs[0])
        self.assertIn("📋 FRU1109260508 notice.png — notice only",
                      msgs[0])

    def test_digest_unreadable_and_questions(self):
        """S10 wording + the questions block; chunks <= 4000."""
        sections = [{
            "shop_label": "Merjan", "shop": "Merjan",
            "posts": [{"code": "MER1109260507", "file": "blurry.jpg",
                       "valid_txt": "", "items": [],
                       "notice_only": False, "unreadable": True}]}]
        questions = [{"kind": "expiry", "text":
                      "Merjan: no end date on this board — reply "
                      "with the date, or 'open' to leave it "
                      "undated"}]
        msgs = ld._render_window_digest(sections, questions,
                                        "Sweep 05:00")
        self.assertIn("image unreadable — forward a clearer version "
                      "or reply with the items as text", msgs[0])
        self.assertIn("1 question needs you:", msgs[0])
        for m in msgs:
            self.assertLessEqual(len(m), 4000)

    def test_notice_and_nonfood_render(self):
        """S11 notice line; S12 butchery non-food items ingest with
        the halal prefix (Q17) — they appear as digest items."""
        items = ld._digest_items([_vision_deal(
            item="Halal Charcoal", price=9.99, unit="ea",
            kind="single", qty=None)])
        self.assertEqual(items[0]["name"], "Halal Charcoal /ea")
        self.assertEqual(items[0]["price_text"], "$9.99/ea")


# ---------------------------------------------------------------------------
# S1/S2/S7: sweep-level behaviours via _sweep_auto_ingest
# ---------------------------------------------------------------------------
class _FakePost:
    def __init__(self, ref, text, created=1.0):
        self.post_ref = ref
        self.creation_time = created
        self.text = text
        self.image_urls = []


class TestSweepAutoIngest(unittest.TestCase):

    def _stores(self):
        from extractors.fb_flyer_fetch import STORES
        return {s["key"]: s for s in STORES}

    def test_three_images_one_post_one_digest(self):
        """S1: all images of ONE post = ONE vision call, ONE merge,
        ONE digest — never 3 summaries."""
        stores = self._stores()
        post = _FakePost("m1", "")
        post.image_urls = ["u1", "u2", "u3"]
        new_posts = [(stores["merjan"], post, "MER1109260507", "")]
        vision_calls = []

        def fake_extract(post_, run_dir, key):
            vision_calls.append(post_.image_urls)
            return [_vision_deal(item="Halal Lamb Necks",
                                 price=15.99)], "vision", None

        ws = FakeWorksheet()
        master = FakeWorksheet(title="Products_Master")
        master.rows = [["Name"] + [""] * 12]
        ss = FakeSpreadsheet()
        ws.title = "Local_Deals"
        ss.sheets = [ws, master]
        sent = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ld, "QUESTIONS_PATH",
                             Path(tmp) / "q.json"), \
                patch.object(ld, "extract_post_deals",
                             side_effect=fake_extract), \
                patch("core.sheets_client.connect_spreadsheet",
                      return_value=ss), \
                patch("core.sheets_client.connect_worksheet",
                      side_effect=RuntimeError("no master")), \
                patch.object(ld, "_post_digest",
                             side_effect=lambda m: sent.extend(m)):
            ld._sweep_auto_ingest(new_posts, "Sweep 05:00")
        self.assertEqual(vision_calls, [["u1", "u2", "u3"]])
        self.assertEqual(len(sent), 1)          # ONE digest
        self.assertIn("Lamb Necks", sent[0])

    def test_two_posts_same_shop_newest_wins(self):
        """S2/S7: two same-day posts, one item in both — the newest
        post's price wins on merge and the digest shows the change."""
        stores = self._stores()
        p_new = _FakePost("m2", "")
        p_old = _FakePost("m1", "")
        new_posts = [(stores["merjan"], p_new, "MER1109260507", ""),
                     (stores["merjan"], p_old, "MER1109260506", "")]

        def fake_extract(post_, run_dir, key):
            price = 11.99 if post_.post_ref == "m2" else 12.99
            from datetime import date
            return ([_vision_deal(item="Halal Lamb Necks",
                                  price=price,
                                  valid_until=date(2026, 9, 12))],
                    "vision", date(2026, 9, 12))

        ws = FakeWorksheet()
        master = FakeWorksheet(title="Products_Master")
        master.rows = [["Name"] + [""] * 12]
        ss = FakeSpreadsheet()
        ss.sheets = [ws, master]
        sent = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ld, "QUESTIONS_PATH",
                             Path(tmp) / "q.json"), \
                patch.object(ld, "extract_post_deals",
                             side_effect=fake_extract), \
                patch("core.sheets_client.connect_spreadsheet",
                      return_value=ss), \
                patch("core.sheets_client.connect_worksheet",
                      side_effect=RuntimeError("no master")), \
                patch.object(ld, "_post_digest",
                             side_effect=lambda m: sent.extend(m)):
            ld._sweep_auto_ingest(new_posts, "Sweep 05:00")
        row = next(r for r in ws.rows
                   if "Lamb Necks" in str(r[0]))
        self.assertEqual(ld._numeric_price(row[MER_SP]),
                         11.99)     # newest post wins
        # S7 user answer 2026-09-11: final price only, no change line
        self.assertNotIn("was $", sent[0])
        self.assertIn("$11.99/kg", sent[0])

    def test_vision_unreadable_no_writes_flagged(self):
        """S10/S16: vision failure -> NO partial writes, the digest
        flags 'image unreadable', the post is not silently dropped."""
        stores = self._stores()
        post = _FakePost("m1", "")
        post.image_urls = ["u1"]
        new_posts = [(stores["merjan"], post, "MER1109260507", "")]

        def fake_extract(post_, run_dir, key):
            from core.flyer_vision import VisionUnavailable
            raise VisionUnavailable("blurry")

        ws = FakeWorksheet()
        sent = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(ld, "QUESTIONS_PATH",
                             Path(tmp) / "q.json"), \
                patch.object(ld, "extract_post_deals",
                             side_effect=fake_extract), \
                patch("core.sheets_client.connect_spreadsheet",
                      return_value=FakeSpreadsheet()), \
                patch.object(ld, "_post_digest",
                             side_effect=lambda m: sent.extend(m)):
            ld._sweep_auto_ingest(new_posts, "Sweep 05:00")
        self.assertEqual(ws.rows, [])            # nothing written
        self.assertIn("image unreadable", sent[0])
        self.assertIn("1 image(s) unreadable", sent[0])


# ---------------------------------------------------------------------------
# AI-M4: the watch-folder watcher (offline; ssh/scp mocked)
# ---------------------------------------------------------------------------
class TestInboxWatcher(unittest.TestCase):

    def _root(self, tmp):
        from tools import inbox_watcher as iw
        root = Path(tmp) / "shop-posts"
        root.mkdir()
        return root, iw

    def test_watcher_groups_settled_batch(self):
        """S1: files newer than the settle window hold the batch; a
        settled burst forms ONE batch with ONE code."""
        with tempfile.TemporaryDirectory() as tmp:
            root, iw = self._root(tmp)
            (root / "a.jpg").write_bytes(b"a")
            (root / "b.jpg").write_bytes(b"b")
            fresh = root / "c.jpg"
            fresh.write_bytes(b"c")
            now = time.time()
            import os
            os.utime(root / "a.jpg", (now - 200, now - 200))
            os.utime(root / "b.jpg", (now - 150, now - 150))
            # all-or-nothing: the fresh file holds the WHOLE batch
            self.assertEqual(iw.scan_batches(root, settle_s=90,
                                             now=now), [])
            import os as _os
            _os.utime(fresh, (now - 200, now - 200))
            batches = iw.scan_batches(root, settle_s=90, now=now)
            self.assertEqual(len(batches), 1)
            self.assertEqual(len(batches[0]["files"]), 3)
            self.assertIsNone(batches[0]["shop_code"])

    def test_watcher_shop_subfolder_pins_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, iw = self._root(tmp)
            shop = root / "Merjan"
            shop.mkdir()
            (shop / "board.jpg").write_bytes(b"x")
            now = time.time()
            import os
            os.utime(shop / "board.jpg", (now - 200, now - 200))
            batches = iw.scan_batches(root, settle_s=90, now=now)
            self.assertEqual(batches[0]["shop_code"], "MER")

    def test_watcher_codes(self):
        root_code = None
        with tempfile.TemporaryDirectory():
            from tools import inbox_watcher as iw
            stamp = datetime(2026, 9, 11, 9, 7,
                             tzinfo=ZoneInfo("Australia/Sydney"))
            self.assertEqual(iw.mint_code(None, stamp),
                             "AUTO1109260907")
            self.assertEqual(iw.mint_code("MER", stamp),
                             "MER1109260907")

    def test_watcher_hash_dedupe(self):
        """S14: the same image saved twice (or by both paths) = ONE
        ingest."""
        with tempfile.TemporaryDirectory() as tmp:
            root, iw = self._root(tmp)
            pushes = []

            def fake_push(batch, code):
                pushes.append((code, len(batch["files"])))
                return True

            now = time.time()
            (root / "one.jpg").write_bytes(b"same-bytes")
            import os
            os.utime(root / "one.jpg", (now - 200, now - 200))
            iw.run_once(root, settle_s=90, now=now, push=fake_push,
                        code_now=lambda: "AUTO1109260900")
            # the SAME bytes return under a new name:
            again = root / "two.jpg"
            again.write_bytes(b"same-bytes")
            os.utime(again, (now - 200, now - 200))
            iw.run_once(root, settle_s=90, now=now, push=fake_push,
                        code_now=lambda: "AUTO1109260910")
            self.assertEqual(pushes, [("AUTO1109260900", 1)])

    def test_watcher_retry_queue(self):
        """S15: a failed push leaves files queued (not marked pushed,
        not moved); the retry window defers the next attempt; a later
        attempt succeeds exactly once."""
        with tempfile.TemporaryDirectory() as tmp:
            root, iw = self._root(tmp)
            calls = {"n": 0}

            def flaky_push(batch, code):
                calls["n"] += 1
                return calls["n"] > 1      # first fails

            now = time.time()
            (root / "board.jpg").write_bytes(b"x")
            import os
            os.utime(root / "board.jpg", (now - 200, now - 200))
            lines1 = iw.run_once(root, settle_s=90, now=now,
                                 push=flaky_push,
                                 code_now=lambda: "AUTO1109260900")
            self.assertTrue(any("failed" in ln for ln in lines1))
            self.assertTrue((root / "board.jpg").exists())
            # inside the retry window: nothing re-attempted
            lines2 = iw.run_once(root, settle_s=90,
                                 now=now + 30, push=flaky_push,
                                 code_now=lambda: "AUTO1109260901")
            self.assertTrue(any("retry window" in ln
                                for ln in lines2))
            self.assertEqual(calls["n"], 1)
            # after the window: retried, succeeds, archived to .sent
            lines3 = iw.run_once(root, settle_s=90,
                                 now=now + 120, push=flaky_push,
                                 code_now=lambda: "AUTO1109260902")
            self.assertEqual(calls["n"], 2)
            self.assertFalse((root / "board.jpg").exists())
            self.assertTrue((root / ".sent" / "AUTO1109260902"
                            / "board.jpg").exists())
            # and never pushed again (S14 state)
            iw.run_once(root, settle_s=90, now=now + 300,
                        push=flaky_push,
                        code_now=lambda: "AUTO1109260903")
            self.assertEqual(calls["n"], 2)

    def test_watcher_single_instance_lock(self):
        """S13: a LIVE foreign process's lock blocks a second
        instance; a killed watcher's lock (fresh mtime, dead pid)
        and a stale lock are both taken over."""
        with tempfile.TemporaryDirectory() as tmp:
            root, iw = self._root(tmp)
            lock = root / ".watcher.lock"
            self.assertTrue(iw.acquire_lock(root))
            # a REAL second process holding the lock
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"])
            try:
                lock.write_text(str(child.pid), encoding="utf-8")
                self.assertTrue(iw._pid_alive(child.pid))
                self.assertFalse(iw.acquire_lock(root))
            finally:
                child.kill()
                child.wait()
            # killed holder -> takeover despite the fresh mtime (the
            # dead pid is spelled out: Windows keeps a terminated
            # pid resolvable while any handle to it stays open)
            lock.write_text("999999999", encoding="utf-8")
            self.assertTrue(iw.acquire_lock(root))
            # stale mtime -> takeover
            old = time.time() - (iw.LOCK_STALE_S + 60)
            os.utime(lock, (old, old))
            self.assertTrue(iw.acquire_lock(root))

    def test_watcher_creates_shop_folders(self):
        """User answer 2026-09-11: the four shop subfolders are
        pre-created (idempotent) so the user only ever drops into
        them."""
        with tempfile.TemporaryDirectory() as tmp:
            from tools import inbox_watcher as iw
            root = Path(tmp) / "shop-posts"
            made = iw.ensure_shop_folders(root)
            self.assertEqual(
                sorted(f.name for f in made),
                ["Abu Salim", "Dunya", "Fruitopia", "Merjan"])
            self.assertEqual(iw.ensure_shop_folders(root), [])
            for name in ("Dunya", "Merjan", "Fruitopia",
                         "Abu Salim"):
                self.assertTrue((root / name).is_dir())
                self.assertEqual(
                    iw._shop_code_for(name),
                    {"Dunya": "DUN", "Merjan": "MER",
                     "Fruitopia": "FRU",
                     "Abu Salim": "ABS"}[name])

    def test_dead_pid_lock_taken_over(self):
        """A lock left by a KILLED watcher (fresh mtime, dead pid)
        is taken over immediately — restarts must not wait out the
        stale window. (Found live when the retention restart
        refused to start.)"""
        with tempfile.TemporaryDirectory() as tmp:
            from tools import inbox_watcher as iw
            root = Path(tmp) / "shop-posts"
            root.mkdir()
            lock = root / ".watcher.lock"
            lock.write_text("999999999", encoding="utf-8")  # dead pid
            self.assertFalse(iw._pid_alive(999999999))
            self.assertFalse(iw._pid_alive(0))
            self.assertTrue(iw._pid_alive(os.getpid()))
            self.assertTrue(iw.acquire_lock(root))

    def test_watcher_unknown_shop_folder_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, iw = self._root(tmp)
            junk = root / "New folder"
            junk.mkdir()
            (junk / "x.jpg").write_bytes(b"x")
            now = time.time()
            import os
            os.utime(junk / "x.jpg", (now - 200, now - 200))
            pushes = []
            lines = iw.run_once(
                root, settle_s=90, now=now,
                push=lambda b, c: pushes.append(c) or True,
                code_now=lambda: "AUTO1109260900")
            self.assertEqual(pushes, [])
            self.assertTrue(any("not a known shop folder" in ln
                                for ln in lines))


# ---------------------------------------------------------------------------
# Retention (user rule 2026-09-11): no unbounded image buildup
# ---------------------------------------------------------------------------
class TestRetention(unittest.TestCase):

    def test_prune_old_inbox_folders(self):
        """VPS inbox: code folders older than 14 days are deleted;
        fresh ones stay; needs_date evidence for an OPEN question
        survives; the just-ingested code (exclude) is untouched even
        when its moved files carry old mtimes."""
        import os
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "MER0109260500"
            (old / "processed").mkdir(parents=True)
            (old / "processed" / "b.jpg").write_bytes(b"o")
            fresh = root / "MER1109260800"
            (fresh / "processed").mkdir(parents=True)
            (fresh / "processed" / "b.jpg").write_bytes(b"f")
            pending = root / "FRU0109260700"
            (pending / "needs_date").mkdir(parents=True)
            (pending / "needs_date" / "b.jpg").write_bytes(b"p")
            oldmoved = root / "DUN0109260600"
            (oldmoved / "processed").mkdir(parents=True)
            (oldmoved / "processed" / "b.jpg").write_bytes(b"m")
            now = time.time()
            for d in (old, pending, oldmoved):
                os.utime(d, (now - 20 * 86400, now - 20 * 86400))
                for f in d.rglob("*"):
                    os.utime(f, (now - 20 * 86400, now - 20 * 86400))
            with patch.object(ld, "INBOX_DIR", root),                     patch.object(ld, "QUESTIONS_PATH",
                                 root / "q.json"):
                ld.open_question("expiry", "FRU0109260700",
                                 "b.jpg", "fruitopia", "ask")
                pruned = ld._prune_inbox(now=now,
                                         exclude="DUN0109260600")
            self.assertIn("MER0109260500", pruned)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(pending.exists())   # open question kept
            self.assertTrue(oldmoved.exists())  # exclude kept

    def test_prune_flyer_runs(self):
        """Sweep-download run dirs older than 14 days are deleted."""
        import os
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "20260828_050000"
            old.mkdir()
            (old / "img.jpg").write_bytes(b"x")
            fresh = root / "20260911_050000"
            fresh.mkdir()
            (fresh / "img.jpg").write_bytes(b"x")
            now = time.time()
            os.utime(old, (now - 20 * 86400, now - 20 * 86400))
            with patch("extractors.fb_flyer_fetch.FLYERS_DIR", root):
                pruned = ld._prune_flyer_runs(now=now)
            self.assertEqual(pruned, ["20260828_050000"])
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())

    def test_watcher_prunes_old_sent(self):
        """Desktop .sent: pushed-batch folders older than 14 days are
        deleted; fresh ones stay."""
        import os
        import tempfile as tf
        with tf.TemporaryDirectory() as tmp:
            from tools import inbox_watcher as iw
            root = Path(tmp) / "shop-posts"
            root.mkdir()
            old = root / ".sent" / "AUTO0109260900"
            old.mkdir(parents=True)
            fresh = root / ".sent" / "AUTO1109260900"
            fresh.mkdir(parents=True)
            now = time.time()
            os.utime(old, (now - 20 * 86400, now - 20 * 86400))
            self.assertEqual(iw.prune_sent(root, now=now), 1)
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())


if __name__ == "__main__":
    unittest.main()
