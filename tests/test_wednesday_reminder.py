"""Wednesday Woolworths-sync reminder (v2 rebuild 2026-09-24): gate
matrix, week idempotence, delivery-truth state (ok-receipt ONLY),
sheet-down path, message sections (instructions + missing list +
parity verdict), and the list cap. Offline — everything patched."""
from __future__ import annotations
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core import wednesday_reminder as wr          # noqa: E402

SYD = ZoneInfo("Australia/Sydney")
WED_0509 = datetime(2026, 9, 23, 5, 9, tzinfo=SYD)   # a Wednesday
WED_1059 = datetime(2026, 9, 23, 10, 59, tzinfo=SYD)
WED_1109 = datetime(2026, 9, 23, 11, 9, tzinfo=SYD)
WED_0459 = datetime(2026, 9, 23, 4, 59, tzinfo=SYD)
THU_0509 = datetime(2026, 9, 24, 5, 9, tzinfo=SYD)

MASTER_HEADER = ["Product_Name", "Category", "Size",
                 "Woolworths_Price", "Brand_Type", "Last_Updated",
                 "Search_Keyword_Woolworths", "Woolworths_Specials",
                 "Rewards_Points", "Keywords", "Sub_Category",
                 "Item_Code", "Preferred"]
# mirrors core.local_deals.TAB_COLUMNS layout (13 cols, code idx 12)
LD_HEADER = ["Product", "Category", "Dunya perm (site)",
             "Dunya special (FB)", "Merjan perm", "Merjan special",
             "Fruitopia perm", "Fruitopia special",
             "Abu Salim perm", "Abu Salim special", "Nazar perm",
             "Comments", "Item_Code"]


def _mrow(name, code, price="", keyword=""):
    row = [""] * 13
    row[0], row[3], row[6], row[11] = name, price, keyword, code
    return row


def _lrow(name, code, dunya_perm=""):
    row = [""] * 13
    row[0], row[2], row[12] = name, dunya_perm, code
    return row


def _grids(n_missing=1, n_wool_only=1, drift=False):
    """Aligned fixture grids: n_missing items with a local price but
    a blank Woolworths side, n_wool_only priced master rows with
    empty LD mirror rows. drift=True swaps two LD codes (middle
    insert)."""
    master = [MASTER_HEADER]
    ld = [LD_HEADER]
    for i in range(n_missing):
        code = f"M{i:02d}X"
        master.append(_mrow(f"Local Item {i}", code))
        ld.append(_lrow(f"Local Item {i}", code, dunya_perm="9.99"))
    for i in range(n_wool_only):
        code = f"W{i:02d}X"
        master.append(_mrow(f"Wool Item {i}", code, price="7.50",
                            keyword="wool item"))
        ld.append(_lrow(f"Wool Item {i}", code))
    if drift and len(ld) >= 3:
        ld[1][12], ld[2][12] = ld[2][12], ld[1][12]
    return master, ld


class TestGate(unittest.TestCase):
    def test_gate_matrix(self):
        cases = [(WED_0509, True), (WED_1059, True),
                 (WED_1109, False), (WED_0459, False),
                 (THU_0509, False)]
        for now, expected in cases:
            self.assertEqual(wr.should_fire(now, state={}), expected,
                             f"{now}")

    def test_gate_week_in_state_noops(self):
        key = wr.week_key(WED_0509)
        self.assertFalse(wr.should_fire(WED_0509, state={key: {}}))
        self.assertEqual(key, "2026-W39")

    def test_force_ignores_gates(self):
        """run_scan(force=True) on a Thursday still fires."""
        sent = []

        def fake_send(token, chat, text, thread_id=None):
            sent.append(text)
            return {"ok": True, "message_id": 77}

        with patch.object(wr, "STATE_PATH",
                          Path(self.id() + ".json")), \
             patch.object(wr, "_read_grids",
                          return_value=_grids()), \
             patch("core.local_deals._send_message", fake_send):
            rc = wr.run_scan(now=THU_0509, force=True)
        self.assertEqual(rc, 0)
        self.assertEqual(len(sent), 1)
        Path(self.id() + ".json").unlink(missing_ok=True)


class TestBuildMessage(unittest.TestCase):
    def test_instructions_and_all_sections(self):
        master, ld = _grids()
        text = wr.build_message(master, ld, WED_0509)
        for fragment in ("Woolworths.docx", "Woolworths_Specials.docx",
                         "grocery_price_cli.py wednesday",
                         "STILL MISSING A WOOLWORTHS PRICE (1)",
                         "[M00X] Local Item 0",
                         "NO LOCAL PRICE YET: 1",
                         "ROW SYNC: \u2705 ALIGNED"):
            self.assertIn(fragment, text)
        self.assertLessEqual(len(text), wr.MAX_MSG_CHARS)

    def test_parity_drift_surfaced(self):
        master, ld = _grids(drift=True)
        text = wr.build_message(master, ld, WED_0509)
        self.assertIn("ROW SYNC: \u26A0\uFE0F MIDDLE_INSERT", text)

    def test_missing_list_capped_with_pointer(self):
        master, ld = _grids(n_missing=30)
        text = wr.build_message(master, ld, WED_0509)
        self.assertIn("(+10 more \u2014 send 'list' for all)", text)
        self.assertIn("[M19X]", text)          # 20 shown, M20.. hidden
        self.assertNotIn("[M20X]", text)
        self.assertLessEqual(len(text), wr.MAX_MSG_CHARS)

    def test_empty_missing_list(self):
        master, ld = _grids(n_missing=0)
        text = wr.build_message(master, ld, WED_0509)
        self.assertIn(wr.EMPTY_LIST_TEXT, text)


class TestRunScanDeliveryTruth(unittest.TestCase):
    """The 2026-09-24 ruling: state is written ONLY on a Telegram-ok
    receipt — the 'fired on VPS but never sent' class can no longer
    eat a week silently."""

    def setUp(self):
        self.state_path = Path(self.id() + ".json")
        self.state_path.unlink(missing_ok=True)

    def tearDown(self):
        self.state_path.unlink(missing_ok=True)

    def test_failed_send_writes_no_state(self):
        def fake_send(token, chat, text, thread_id=None):
            return {"ok": False, "message_id": None}

        with patch.object(wr, "STATE_PATH", self.state_path), \
             patch.object(wr, "_read_grids",
                          return_value=_grids()), \
             patch("core.local_deals._send_message", fake_send):
            rc = wr.run_scan(now=WED_0509)
        self.assertEqual(rc, 1)
        self.assertFalse(self.state_path.exists())

    def test_ok_send_writes_state_with_message_id(self):
        def fake_send(token, chat, text, thread_id=None):
            return {"ok": True, "message_id": 4242}

        with patch.object(wr, "STATE_PATH", self.state_path), \
             patch.object(wr, "_read_grids",
                          return_value=_grids()), \
             patch("core.local_deals._send_message", fake_send):
            rc = wr.run_scan(now=WED_0509)
        self.assertEqual(rc, 0)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        entry = state["2026-W39"]
        self.assertTrue(entry["sent"])
        self.assertEqual(entry["message_id"], 4242)
        self.assertTrue(entry["sheet_ok"])

    def test_sheet_down_still_sends_instructions(self):
        captured = {}

        def fake_send(token, chat, text, thread_id=None):
            captured["text"] = text
            return {"ok": True, "message_id": 99}

        def boom():
            raise RuntimeError("google is down")

        with patch.object(wr, "STATE_PATH", self.state_path), \
             patch.object(wr, "_read_grids", boom), \
             patch("core.local_deals._send_message", fake_send):
            rc = wr.run_scan(now=WED_0509)
        self.assertEqual(rc, 0)
        self.assertIn("grocery_price_cli.py wednesday",
                      captured["text"])
        self.assertIn("Couldn't read the sheet", captured["text"])
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertFalse(state["2026-W39"]["sheet_ok"])

    def test_already_sent_week_never_resends(self):
        sent = []

        def fake_send(token, chat, text, thread_id=None):
            sent.append(text)
            return {"ok": True, "message_id": 1}

        self.state_path.write_text(
            json.dumps({"2026-W39": {"sent": True}}), encoding="utf-8")
        with patch.object(wr, "STATE_PATH", self.state_path), \
             patch("core.local_deals._send_message", fake_send):
            rc = wr.run_scan(now=WED_0509)
        self.assertEqual(rc, 0)
        self.assertEqual(sent, [])

    def test_dry_run_prints_and_writes_nothing(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), \
             patch.object(wr, "STATE_PATH", self.state_path), \
             patch.object(wr, "_read_grids",
                          return_value=_grids()):
            rc = wr.run_scan(now=WED_0509, send=False)
        self.assertEqual(rc, 0)
        self.assertIn("WEDNESDAY WOOLWORTHS SYNC", buf.getvalue())
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main()
