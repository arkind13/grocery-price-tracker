"""T-set 4 — Wednesday v2 (spec §10): plan_sync semantics (prices,
N/A / unavailable / GONE-preserved markers, multibuy deal rates,
H deal-end clears, no auto-add), the A2 parity step (aligned /
bottom-append auto-mirror with codes / middle-insert abort), the run
pipeline (posts via a fake sender, dry-run, 4000-char split).
Offline: FakeSheet pairs (test_v2_batch harness), docx built
in-test via python-docx, tmp registry (conftest isolation).
Zero skips."""
from __future__ import annotations
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.v2_wednesday import (                   # noqa: E402
    LISTS_TOPIC_ID, SPECIALS_TOPIC_ID, apply_writes, match_index,
    parity_step, plan_sync, run,
)
from extractors.models import ProductItem         # noqa: E402
from tools.parity_audit import (                  # noqa: E402
    MIDDLE_INSERT_ALERT, audit as audit_fn,
)

TODAY = date(2026, 9, 10)

MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]


def _master_row(name, code, ww="", keyword="", specials=""):
    row = [""] * 13
    row[0], row[3], row[6], row[7], row[10], row[11] = (
        name, ww, keyword, specials, "butchery", code)
    return row


class FakeWS:
    """Minimal gspread worksheet double (values + clear + update)."""

    def __init__(self, rows):
        self._values = [list(r) for r in rows]
        self.clears = 0
        self.updates = []

    def get_all_values(self):
        return [list(r) for r in self._values]

    def clear(self):
        self.clears += 1

    def freeze(self, rows=0):
        pass

    def update(self, *, values, range_name):
        self.updates.append(range_name)
        self._values = [list(r) for r in values]


class FakeSheet:
    """connect_spreadsheet double: 13-col master + 11-col LD tabs."""

    def __init__(self, master, ld):
        self.master_ws = master
        self.ld_ws = ld

    def worksheet(self, name):
        return self.master_ws if name == "Products_Master" \
            else self.ld_ws


def _item(name, price=None, special_desc="", is_special=False):
    return ProductItem(store="woolworths", raw_name=name, price=price,
                       is_special=is_special,
                       special_desc=special_desc)


def _fixture():
    """Aligned pair (master order == LD item order):
    Tomato (priced+keyword) / Halal Beef Mince (keyword, unpriced) /
    Cheddar Block (GONE+keyword) / Halal Lamb Shoulder (no keyword,
    LD price -> missing list)."""
    master = [MASTER_HEADER,
              _master_row("Tomato", "EYF", ww="$0.54",
                          keyword="woolworths tomato"),
              _master_row("Halal Beef Mince 500g", "AUG",
                          keyword="halal beef mince"),
              _master_row("Woolworths Cheddar Block 1kg", "CHD",
                          ww="GONE", keyword="cheddar cheese block"),
              _master_row("Halal Lamb Shoulder", "HLS")]
    ld = [["Product", "", "", "", "", "", "", "", "", "", "", ""],
          ["Tomato", "", "", "", "", "0.90", "", "", "", "", "",
           "EYF"],
          ["Halal Beef Mince 500g", "", "9.20", "", "", "", "", "",
           "", "", "", "AUG"],
          ["Woolworths Cheddar Block 1kg", "", "", "", "", "", "",
           "", "", "", "", "CHD"],
          ["Halal Lamb Shoulder", "12.99", "", "", "", "", "", "",
           "", "", "", "HLS"]]
    return FakeWS(master), FakeWS(ld)


class TestMatchIndex(unittest.TestCase):
    def test_normalized_keyword_skips_blank_and_header(self):
        master, _ld = _fixture()
        index = match_index(master._values)
        self.assertEqual(index, {"woolworths tomato": 1,
                                 "halal beef mince": 2,
                                 "cheddar cheese block": 3})
        self.assertNotIn("product_name", index)   # header not indexed


class TestPlanSync(unittest.TestCase):
    def setUp(self):
        self.master, self.ld = _fixture()

    def _plan(self, main=(), specials=()):
        return plan_sync(self.master._values, list(main),
                         list(specials), TODAY)

    def test_1_keyword_match_writes_2dp_price(self):
        plan = self._plan(main=[_item("Woolworths Tomato", 0.6)])
        self.assertIn((1, 3, "$0.60"), plan["writes"])
        self.assertEqual(plan["matched"], 1)

    def test_2_absent_row_na_and_gone_preserved(self):
        # beef mince has a keyword but is absent from the main docx
        # -> N/A <today>; cheddar is GONE -> GONE SURVIVES.
        plan = self._plan(main=[_item("Woolworths Tomato", 0.6)])
        self.assertIn((2, 3, f"N/A {TODAY.isoformat()}"),
                      plan["writes"])
        gone_writes = [w for w in plan["writes"]
                       if w[0] == 3 and w[1] == 3]
        self.assertEqual(gone_writes, [])   # GONE row never written
        self.assertIn("Halal Beef Mince 500g", plan["na"])

    def test_3_real_price_overwrites_gone_and_na(self):
        self.master._values[2][3] = "N/A 2026-09-03"   # beef mince
        plan = self._plan(main=[
            _item("Woolworths Tomato", 0.6),
            _item("Halal Beef Mince", 9.5),
            _item("Cheddar Cheese Block", 8.2),
        ])
        writes = {(i, c): v for i, c, v in plan["writes"]}
        self.assertEqual(writes[(2, 3)], "$9.50")    # over N/A
        self.assertEqual(writes[(3, 3)], "$8.20")    # over GONE
        self.assertEqual(plan["na"], [])

    def test_4_listed_but_unpriced_unavailable(self):
        plan = self._plan(main=[_item("Woolworths Tomato", 0.0)])
        self.assertIn((1, 3, f"unavailable {TODAY.isoformat()}"),
                      plan["writes"])
        self.assertEqual(plan["unavailable"], ["Tomato"])
        self.assertEqual(plan["matched"], 0)

    def test_5_multibuy_special_rate_and_h_cell(self):
        plan = self._plan(
            main=[_item("Woolworths Tomato", 0.6)],
            specials=[_item("Cheddar Cheese Block", 6.0,
                            special_desc="2 for $6.00",
                            is_special=True)])
        writes = {(i, c): v for i, c, v in plan["writes"]}
        self.assertEqual(writes[(3, 3)], "$3.00")    # per-unit rate
        self.assertEqual(writes[(3, 7)], "multi-buy 2/$6.00")
        self.assertEqual(plan["multibuy"],
                         ["Woolworths Cheddar Block 1kg"])

    def test_6_deal_ended_h_cleared_d_normal_price(self):
        self.master._values[3][7] = "multi-buy 2/$7.00"
        plan = self._plan(
            main=[_item("Woolworths Tomato", 0.6),
                  _item("Cheddar Cheese Block", 8.2)])
        writes = {(i, c): v for i, c, v in plan["writes"]}
        self.assertEqual(writes[(3, 3)], "$8.20")    # normal price
        self.assertEqual(writes[(3, 7)], "")         # H cleared
        self.assertEqual(plan["cleared_h"],
                         ["Woolworths Cheddar Block 1kg"])

    def test_7_unmatched_docx_line_report_only(self):
        plan = self._plan(main=[
            _item("Woolworths Tomato", 0.6),
            _item("Woolworths Not Tracked Yoghurt", 4.0)])
        self.assertEqual(plan["unmatched"],
                         ["Woolworths Not Tracked Yoghurt"])
        self.assertFalse(any(w[0] not in (1, 2, 3)
                             for w in plan["writes"]))

    def test_8_specials_only_no_keyword_report_only(self):
        plan = self._plan(
            specials=[_item("Fruitopia Untracked Juice", 3.0,
                            special_desc="save $0.50",
                            is_special=True)])
        self.assertEqual(plan["unmatched"],
                         ["Fruitopia Untracked Juice"])
        self.assertEqual(plan["multibuy"], [])
        # no write may touch a non-keyword row (HLS, idx 4) or any
        # specials-side cell — the juice line is report-only (§4.2).
        self.assertFalse(any(w[0] == 4 or w[1] == 7
                             for w in plan["writes"]))

    def test_deal_end_sweep_never_touches_blank_keyword_rows(self):
        # HLS has no keyword: its H stays untouched — Wednesday only
        # ever syncs keyword rows (§17.6).
        self.master._values[4][7] = "save $1.00"
        plan = self._plan(main=[_item("Woolworths Tomato", 0.6)])
        self.assertFalse(any(w[0] == 4 for w in plan["writes"]))

    def test_specials_only_skips_main_pass(self):
        """--specials-only (user rule 2026-09-10, weeks between main
        list cleanups): NO main-docx D writes, NO N/A sweep (manual
        prices survive), no main-docx unmatched noise; the specials
        docx still acts (H + deal rate) and deal-end clears still run.
        """
        self.master._values[2][3] = "12.50"    # manual D price
        self.master._values[2][7] = "multi-buy 2/$8.00"  # stale deal
        plan = plan_sync(
            self.master._values,
            [_item("Woolworths Tomato", 0.6)],      # stale main docx
            [_item("Cheddar Cheese Block", 6.0,
                   special_desc="2 for $6.00", is_special=True)],
            TODAY, specials_only=True)
        writes = {(i, c): v for i, c, v in plan["writes"]}
        self.assertNotIn((1, 3), writes)       # tomato D untouched
        self.assertNotIn((2, 3), writes)       # beef mince NOT N/A'd
        self.assertEqual(plan["na"], [])
        self.assertEqual(plan["matched"], 0)
        self.assertEqual(plan["unmatched"], [])  # main noise suppressed
        self.assertEqual(plan["cleared_h"],
                         ["Halal Beef Mince 500g"])  # deal-end sweep
        self.assertEqual(writes.get((2, 7)), "")
        # the specials docx still acts: rate + H terms
        self.assertEqual(writes[(3, 3)], "$3.00")
        self.assertEqual(writes[(3, 7)], "multi-buy 2/$6.00")


class TestApplyWrites(unittest.TestCase):
    def test_single_clear_update_and_noop(self):
        master, _ld = _fixture()
        apply_writes(master, master._values,
                     [(1, 3, "$0.60"), (3, 3, "GONE")])
        self.assertEqual(master.clears, 1)
        self.assertEqual(master.updates, ["A1:M5"])
        self.assertEqual(master._values[1][3], "$0.60")
        apply_writes(master, master._values, [])
        self.assertEqual(master.clears, 1)       # no-op on empty plan


class TestParityStep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("core.item_codes.REGISTRY_PATH",
                        Path(self.tmp.name) / "registry.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_aligned_single_clean_line(self):
        master, ld = _fixture()
        report = parity_step(master._values, ld._values, ld,
                             master_ws=master)
        self.assertEqual(report, "ALIGNED")
        self.assertEqual(master.clears, 0)
        self.assertEqual(ld.clears, 0)

    def test_bottom_append_auto_mirror_both_tabs_with_codes(self):
        from core import item_codes
        # Scenario A: user added a master row at the end (no code
        # yet) -> blank LD mirror with a freshly reserved code.
        master, ld = _fixture()
        master._values.append(_master_row("New User Row", ""))
        self.assertEqual(audit_fn(master._values, ld._values)
                         ["status"], "bottom_append")
        report = parity_step(master._values, ld._values, ld,
                             master_ws=master)
        self.assertIn("BOTTOM_APPEND", report)
        self.assertIn("mirrored -> LD row 6: New User Row", report)
        new_ld = ld._values[-1]
        self.assertEqual(new_ld[0], "New User Row")
        self.assertTrue(item_codes.is_valid_code(new_ld[11]))
        # the code is the PAIR KEY: stamped on BOTH sides
        self.assertEqual(master._values[-1][11], new_ld[11])
        self.assertIn(new_ld[11],
                      item_codes.retired_codes(
                          item_codes.load_registry()))
        self.assertEqual(audit_fn(master._values, ld._values)
                         ["status"], "aligned")
        self.assertEqual(ld.clears, 1)
        self.assertEqual(ld.updates, ["A1:L6"])
        self.assertEqual(master.clears, 1)
        self.assertEqual(master.updates, ["A1:M6"])

        # Scenario B: extra coded LD item row at the end -> blank
        # master mirror reusing that code (EXL).
        master, ld = _fixture()
        ld._values.append(["Extra Local Item", "", "", "", "", "",
                           "", "", "", "", "", "EXL"])
        self.assertEqual(audit_fn(master._values, ld._values)
                         ["status"], "bottom_append")
        report = parity_step(master._values, ld._values, ld,
                             master_ws=master)
        self.assertIn("mirrored -> master row 6: Extra Local Item",
                      report)
        self.assertEqual(master._values[-1][0], "Extra Local Item")
        self.assertEqual(master._values[-1][11], "EXL")
        self.assertEqual(audit_fn(master._values, ld._values)
                         ["status"], "aligned")
        # counts equal after: named master rows == LD item rows
        # (parity_audit's own item-row exemption, incl. the header)
        from tools.parity_audit import is_ld_item_row
        named = [r for r in master._values[1:] if r[0]]
        ld_items = [r for i, r in enumerate(ld._values)
                    if is_ld_item_row(i, r)]
        self.assertEqual(len(named), len(ld_items))
        self.assertEqual(master.clears, 1)
        self.assertEqual(master.updates, ["A1:M6"])
        self.assertEqual(ld.clears, 0)

    def test_middle_insert_prints_verbatim_alert_and_aborts(self):
        master, ld = _fixture()
        ld._values[3][11] = "ZZQ"          # code break mid-sequence
        buf = io.StringIO()
        with redirect_stdout(buf):
            report = parity_step(master._values, ld._values, ld,
                                 master_ws=master)
        self.assertEqual(report, "ABORT")
        self.assertIn(MIDDLE_INSERT_ALERT.format(n=4), buf.getvalue())
        self.assertEqual(master.clears, 0)
        self.assertEqual(ld.clears, 0)

    def test_heal_names_coded_blank_ld_row_from_master_pair(self):
        """User directive 2026-09-12: a Wool-only LD mirror row that
        lost its name (coded, Col-A-blank) is re-named from the
        master row sharing its Item_Code — no blank lines."""
        master, ld = _fixture()
        ld._values[3][0] = ""              # Cheddar row name lost
        report = parity_step(master._values, ld._values, ld,
                             master_ws=master)
        self.assertIn("healed: LD row 4 named "
                      "'Woolworths Cheddar Block 1kg'", report)
        self.assertEqual(ld._values[3][0],
                         "Woolworths Cheddar Block 1kg")
        self.assertEqual(ld.clears, 1)     # heal written immediately
        self.assertEqual(audit_fn(master._values, ld._values)
                         ["status"], "aligned")

    def test_heal_strips_legacy_structural_rows(self):
        """Legacy furniture (stamp row / section titles) is removed
        by the parity step — LD mirrors the master row-for-row."""
        master, ld = _fixture()
        ld._values.insert(1, ["Prices valid until",
                              "n/a (live site)"] + [""] * 10)
        ld._values.insert(3, ["FRUITS"] + [""] * 11)
        report = parity_step(master._values, ld._values, ld,
                             master_ws=master)
        self.assertIn("structural row 'Prices valid until' removed",
                      report)
        self.assertIn("structural row 'FRUITS' removed", report)
        names = [str(r[0]).strip() for r in ld._values]
        self.assertNotIn("Prices valid until", names)
        self.assertNotIn("FRUITS", names)
        self.assertNotIn("BUTCHERY", names)
        self.assertEqual(audit_fn(master._values, ld._values)
                         ["status"], "aligned")

    def test_middle_insert_single_row_auto_moved_to_bottom(self):
        """User directive 2026-09-12: 'anything not in order to be
        fixed by it' — a genuine single-row mid-tab insert is moved
        to the tab's bottom automatically, then parity is aligned."""
        master, ld = _fixture()
        # A new item inserted in the MIDDLE of the LD tab (code new,
        # not yet mirrored): rows 3.. shift down by one.
        ld._values.insert(2, ["Halal Chicken Mince", "", "", "", "",
                              "", "", "", "", "", "", "NEW1"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            report = parity_step(master._values, ld._values, ld,
                                 master_ws=master)
        self.assertIn("healed: LD row 3 ('Halal Chicken Mince') "
                      "moved to the bottom", report)
        self.assertIn("BOTTOM_APPEND", report)   # mirror followed
        self.assertEqual(ld._values[-1][0], "Halal Chicken Mince")
        self.assertEqual(audit_fn(master._values, ld._values)
                         ["status"], "aligned")
        self.assertEqual(ld.clears, 1)   # the single mirror write

    def test_middle_insert_swap_is_never_auto_repaired(self):
        """A code SWAP (reorder/deletion class) is not a single-row
        insert: no move, verbatim alert, ABORT — no writes."""
        master, ld = _fixture()
        ld._values[2][11], ld._values[3][11] = \
            ld._values[3][11], ld._values[2][11]     # AUG <-> CHD
        buf = io.StringIO()
        with redirect_stdout(buf):
            report = parity_step(master._values, ld._values, ld,
                                 master_ws=master)
        self.assertEqual(report, "ABORT")
        self.assertIn(MIDDLE_INSERT_ALERT.format(n=4), buf.getvalue())
        self.assertEqual(master.clears, 0)
        self.assertEqual(ld.clears, 0)


class TestRunPipeline(unittest.TestCase):
    """run() end-to-end on fakes: patched parse_inputs +
    connect_spreadsheet + sender. Zero network, zero real sheet."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        reg = patch("core.item_codes.REGISTRY_PATH",
                    Path(self.tmp.name) / "registry.json")
        reg.start()
        self.addCleanup(reg.stop)
        self.master, self.ld = _fixture()
        self.sends: list = []

        def fake_send(bot_token, chat_id, text, thread_id=None):
            self.sends.append({"text": text, "thread_id": thread_id})
            return {"ok": True, "message_id": 100 + len(self.sends),
                    "chat_id": chat_id, "thread_id": thread_id}

        for p in (
            patch("core.v2_wednesday.parse_inputs",
                  return_value=([_item("Woolworths Tomato", 0.6)],
                                [])),
            patch("core.sheets_client.connect_spreadsheet",
                  return_value=FakeSheet(self.master, self.ld)),
            patch("core.local_deals._send_message", fake_send),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_9_aligned_run_completes_two_post_renders(self):
        rc = run()
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.sends), 2)
        self.assertEqual(self.sends[0]["thread_id"],
                         SPECIALS_TOPIC_ID)
        self.assertEqual(self.sends[1]["thread_id"], LISTS_TOPIC_ID)
        self.assertIn("No active specials", self.sends[0]["text"])
        self.assertIn("[HLS] Halal Lamb Shoulder",
                      self.sends[1]["text"])
        self.assertEqual(self.master.updates, ["A1:M5"])
        self.assertEqual(self.master._values[1][3], "$0.60")

    def test_11_middle_insert_aborts_run_no_writes_no_posts(self):
        self.ld._values[3][11] = "ZZQ"
        rc = run()
        self.assertEqual(rc, 1)
        self.assertEqual(self.sends, [])
        self.assertEqual(self.master.clears, 0)
        self.assertEqual(self.ld.clears, 0)
        self.assertEqual(self.master.updates, [])

    def test_12_dry_run_no_writes_no_posts_full_report(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run(dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.sends, [])
        self.assertEqual(self.master.clears, 0)
        self.assertEqual(self.master.updates, [])
        out = buf.getvalue()
        self.assertIn("matched=1", out)
        self.assertIn("writes=2", out)   # tomato price + mince N/A
        self.assertIn("n/a: Halal Beef Mince 500g", out)
        self.assertIn("elapsed=", out)

    def test_send_false_writes_but_never_posts(self):
        rc = run(send=False)
        self.assertEqual(rc, 0)
        self.assertEqual(self.sends, [])
        self.assertEqual(self.master.updates, ["A1:M5"])


class TestListPostSplit(unittest.TestCase):
    def test_13_over_4000_render_splits_within_budget(self):
        from core.telegram_format import split_message
        from core.v2_read import missing_list, parse_ld_row, \
            parse_master_row, render_list

        master = [MASTER_HEADER]
        ld = [["Product", "", "", "", "", "", "", "", "", "", "", ""],
              ["Prices valid until", "", "", "", "", "", "", "",
               "", "", "", ""],
              ["FRUITS"] + [""] * 11]
        for i in range(120):
            code = f"C{i:03d}"
            name = f"Item Number {i:03d} Large Family Pack 1kg"
            row = [""] * 13
            row[0], row[10], row[11] = name, "butchery", code
            master.append(row)
            ld.append([name, "", "", "", "", f"{i}.49", "", "", "",
                       "", "", code])
        master_rows = [m for m in (parse_master_row(i, r)
                                   for i, r in
                                   enumerate(master[1:], 2)) if m]
        ld_rows = [l for l in (parse_ld_row(i, r)
                               for i, r in enumerate(ld)) if l]
        items = missing_list(master_rows, ld_rows)
        text = render_list(items)
        self.assertGreater(len(text), 4000)
        chunks = split_message(text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4000)
        joined = "\n".join(chunks)
        for i in range(120):
            self.assertIn(f"[C{i:03d}]", joined)
        self.assertTrue(chunks[0].startswith("📋"))


if __name__ == "__main__":
    unittest.main()
