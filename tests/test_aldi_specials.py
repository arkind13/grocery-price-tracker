"""Aldi Wed/Sat specials job (spec §4): gate matrix, idempotence,
renderer goldens, split cap, failure path, hero non-fatal, and the
no-sheet guarantee. Offline — everything patched; zero network."""
from __future__ import annotations
import json
import sys, unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors.models import ProductItem
from core import aldi_specials as aj

SYD = ZoneInfo("Australia/Sydney")
WED_5AM = datetime(2026, 9, 9, 5, 8, tzinfo=SYD)     # a Wednesday
SAT_5AM = datetime(2026, 9, 12, 5, 8, tzinfo=SYD)    # a Saturday
FRI_5AM = datetime(2026, 9, 11, 5, 8, tzinfo=SYD)    # a Friday
WED_6AM = datetime(2026, 9, 9, 6, 8, tzinfo=SYD)
WED_10AM = datetime(2026, 9, 9, 10, 8, tzinfo=SYD)
WED_11AM = datetime(2026, 9, 9, 11, 8, tzinfo=SYD)
WED_3PM = datetime(2026, 9, 9, 15, 8, tzinfo=SYD)


def _item(name, price=9.99, size="500 g", brand="BRAND",
          theme="Grocery Specials", hero=""):
    it = ProductItem(store="aldi", raw_name=name, price=price,
                     size=size, brand=brand)
    it._theme_categories = [theme]
    it._hero_asset = hero
    return it


class TestGate(unittest.TestCase):
    def test_gate_matrix_retry_window(self):
        """2026-09-24 delivery-truth ruling: fires Wed/Sat 05:xx
        through 10:xx Sydney (hourly retries after a failed send),
        never outside that window."""
        cases = [(WED_5AM, True), (SAT_5AM, True),
                 (WED_6AM, True), (WED_10AM, True),
                 (WED_11AM, False), (FRI_5AM, False),
                 (WED_3PM, False)]
        for now, expected in cases:
            fire, date_iso = aj.should_fire(now, state={})
            self.assertEqual(fire, expected, f"{now}")
            self.assertEqual(date_iso, now.date().isoformat())

    def test_gate_already_posted_date_noops(self):
        fire, _ = aj.should_fire(WED_5AM,
                                 state={WED_5AM.date().isoformat(): {}})
        self.assertFalse(fire)

    def test_gate_terminal_failed_date_noops(self):
        """A permanent failure blocks pointless retries for the date."""
        fire, _ = aj.should_fire(
            WED_5AM,
            state={WED_5AM.date().isoformat():
                   {"posted": False, "terminal": True}})
        self.assertFalse(fire)

    def test_advance_visibility_no_early_fire(self):
        """V3: Saturday's drop visible on Friday must NOT fire Friday."""
        fire, date_iso = aj.should_fire(FRI_5AM, state={})
        self.assertFalse(fire)
        self.assertEqual(date_iso, "2026-09-11")


class TestRender(unittest.TestCase):
    def _items(self):
        return [_item("Salmon Gravalax 250g", 10.99, size="250 g",
                      theme="Limited Time Only Meat"),
                _item("Peanut Puffs 200g", 2.99,
                      theme="Grocery Specials"),
                _item("Pretzels 200g", 5.99,
                      theme="Grocery Specials"),
                _item("Deluxe Gazebo 3m", 129.00, size="", brand="",
                      theme="Camping")]

    def test_render_includes_every_theme_and_item(self):
        blocks = aj.render_specials_post(
            self._items(), "Available from Wed 9th September",
            "2026-09-09")
        text = "\n\n".join(blocks)
        for theme in ("LIMITED TIME ONLY MEAT", "GROCERY SPECIALS",
                      "CAMPING"):
            self.assertIn(theme, text)
        for name in ("Salmon Gravalax 250g", "Peanut Puffs 200g",
                     "Pretzels 200g", "Deluxe Gazebo 3m"):
            self.assertIn(name, text)
        self.assertIn("4 special buys", text)

    def test_render_theme_groups_and_dividers(self):
        blocks = aj.render_specials_post(
            self._items(), "Available from Wed 9th September",
            "2026-09-09")
        text = "\n\n".join(blocks)
        self.assertIn("🥩 LIMITED TIME ONLY MEAT", text)
        self.assertIn("🛒 GROCERY SPECIALS", text)
        self.assertIn("⛺ CAMPING", text)
        self.assertIn("─" * 28, text)
        self.assertIn("🔵 ALDI SPECIAL BUYS — Wednesday 9 September 🛒",
                      text)

    def test_render_two_line_entries(self):
        blocks = aj.render_specials_post(
            self._items(), "Available from Wed 9th September",
            "2026-09-09")
        text = "\n\n".join(blocks)
        self.assertIn("💵 $10.99 · 250 g · BRAND", text)
        self.assertIn("💵 $129.00", text)   # no size/brand parts

    def test_split_blocks_char_cap(self):
        big = "\n\n".join(f"para {i} " + "x" * 500 for i in range(40))
        for b in aj._split_blocks(big):
            self.assertLessEqual(len(b), aj.MAX_MSG_CHARS)

    def test_split_suffixes_one_of_n(self):
        big = "\n\n".join(f"para {i} " + "x" * 2000 for i in range(6))
        blocks = aj._split_blocks(big)
        self.assertGreater(len(blocks), 1)
        self.assertTrue(blocks[0].endswith("(1/%d)" % len(blocks)))
        self.assertTrue(blocks[-1].endswith("(%d/%d)"
                                            % (len(blocks), len(blocks))))

    def test_split_never_cuts_an_item(self):
        items = [_item(f"Item {i:02d}", 1.0 + i,
                       theme="Grocery Specials") for i in range(120)]
        blocks = aj.render_specials_post(items, "t", "2026-09-09")
        text = "\n\n".join(blocks)
        for i in range(120):
            self.assertIn(f"Item {i:02d}", text)

    def test_empty_items_render_nothing(self):
        self.assertEqual(aj.render_specials_post([], "t", "2026-09-09"),
                         [])


class TestWarning(unittest.TestCase):
    def test_warning_single_line_shape(self):
        line = aj.render_warning("Wednesday", RuntimeError("x"))
        self.assertTrue(line.startswith("⚠️ ALDI specials unavailable"))
        self.assertIn("Wednesday", line)
        self.assertNotIn("\n", line)


class TestRunScan(unittest.TestCase):
    def setUp(self):
        """Isolate the state file: these tests must NEVER touch the
        real data/aldi_specials_state.json (the 2026-09-24 container
        run polluted + wiped the PRODUCTION state via the old global
        save/restore pattern)."""
        import tempfile as tf
        self._tmp = tf.TemporaryDirectory()
        state_path = Path(self._tmp.name) / "aldi_state.json"
        state_path.write_text("{}", encoding="utf-8")
        patcher = patch.object(aj, "STATE_PATH", state_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _promo(self):
        return {"key": "2026-09-09",
                "title": "Available from Wed 9th September"}

    def test_offday_silent_noop(self):
        with patch("core.sydney_time.sydney_now",
                   return_value=FRI_5AM):
            rc = aj.run_scan()
        self.assertEqual(rc, 0)

    def test_failure_posts_single_warning(self):
        from extractors.aldi_extractor import AldiAPIError
        sent = []
        with patch("core.sydney_time.sydney_now",
                   return_value=WED_5AM), \
             patch("extractors.aldi_extractor.find_promotion",
                   return_value=self._promo()), \
             patch("extractors.aldi_extractor.fetch_aldi_specials",
                   side_effect=AldiAPIError("HTTP 403")), \
             patch.object(aj, "_send_message",
                          side_effect=lambda t, x, th:
                          sent.append(x) or {"ok": True}):
            rc = aj.run_scan(send=True)
        self.assertEqual(rc, 1)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith("⚠️ ALDI specials"))
        self.assertEqual(aj._load_state(), {})   # no state on failure

    def test_failure_never_raises(self):
        from extractors.aldi_extractor import AldiAPIError
        with patch("core.sydney_time.sydney_now",
                   return_value=WED_5AM), \
             patch("extractors.aldi_extractor.find_promotion",
                   side_effect=AldiAPIError("net down")), \
             patch.object(aj, "_send_message", return_value={"ok": 1}):
            self.assertEqual(aj.run_scan(send=True), 1)

    def test_success_posts_hero_and_blocks_then_state(self):
        items = self._scan_items()
        msgs, photos = [], []
        with patch("core.sydney_time.sydney_now",
                   return_value=WED_5AM), \
             patch("extractors.aldi_extractor.find_promotion",
                   return_value=self._promo()), \
             patch("extractors.aldi_extractor.fetch_aldi_specials",
                   return_value=items), \
             patch.object(aj, "_send_message",
                          side_effect=lambda t, x, th:
                          msgs.append(x) or {"ok": True,
                                             "message_id": 1}), \
             patch.object(aj, "_send_photo",
                          side_effect=lambda t, u, c, th:
                          photos.append(u) or {"ok": True}):
            rc = aj.run_scan(send=True)
        self.assertEqual(rc, 0)
        self.assertEqual(len(photos), 1)
        self.assertIn("640", photos[0])
        self.assertGreaterEqual(len(msgs), 1)
        self.assertIn("2026-09-09", aj._load_state())

    def test_hero_photo_nonfatal(self):
        items = self._scan_items(hero="")
        with patch("core.sydney_time.sydney_now",
                   return_value=WED_5AM), \
             patch("extractors.aldi_extractor.find_promotion",
                   return_value=self._promo()), \
             patch("extractors.aldi_extractor.fetch_aldi_specials",
                   return_value=items), \
             patch.object(aj, "_send_photo",
                          return_value={"ok": False}), \
             patch.object(aj, "_send_message",
                          return_value={"ok": True,
                                        "message_id": 2}):
            self.assertEqual(aj.run_scan(send=True), 0)

    def test_same_date_refire_noop(self):
        aj._save_state({"2026-09-09": {"posted": True}})
        fetched = []
        with patch("core.sydney_time.sydney_now",
                   return_value=WED_5AM), \
             patch("extractors.aldi_extractor.find_promotion",
                   side_effect=lambda d:
                   fetched.append(d) or self._promo()):
            rc = aj.run_scan(send=True)
        self.assertEqual(rc, 0)
        self.assertEqual(fetched, [])   # never hit the API

    def test_no_sheet_imports(self):
        source = Path(aj.__file__).read_text(encoding="utf-8")
        for banned in ("sheets_client", "connect_spreadsheet",
                       "get_all_values", "worksheet("):
            self.assertNotIn(banned, source)

    @staticmethod
    def _scan_items(hero="https://img/{width}/{slug}"):
        return [_item("Salmon Gravalax 250g", 10.99,
                      theme="Limited Time Only Meat", hero=hero),
                _item("Peanut Puffs 200g", 2.99,
                      theme="Grocery Specials", hero=hero)]


class TestRunScanDeliveryTruth(unittest.TestCase):
    """2026-09-24 user ruling: 'it needs to understand WHY it
    failed — if it failed for a valid reason 1000s of retries will
    not fix it'. Transient failures retry (state stays clean,
    exit 1); PERMANENT failures stop for the day with the reason
    recorded (terminal state, exit 2); the date is marked posted
    only when Telegram confirmed at least one block."""

    def setUp(self):
        import tempfile as tf
        self._tmp = tf.TemporaryDirectory()
        self.state_path = Path(self._tmp.name) / "aldi_state.json"
        self.state_path.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, receipt_or_list, hero_receipt=None, n_items=2):
        items = [_item(f"Item {i} filler name", 10.99 + i)
                 for i in range(n_items)]
        receipts = (receipt_or_list if isinstance(receipt_or_list, list)
                    else [receipt_or_list])
        calls = {"i": 0}

        def fake_send(t, x, th):
            idx = min(calls["i"], len(receipts) - 1)
            calls["i"] += 1
            return receipts[idx]

        with patch("core.sydney_time.sydney_now",
                   return_value=WED_5AM), \
             patch("extractors.aldi_extractor.find_promotion",
                   return_value={"key": "2026-09-09",
                                 "title": "Available from Wed"}), \
             patch("extractors.aldi_extractor.fetch_aldi_specials",
                   return_value=items), \
             patch.object(aj, "STATE_PATH", self.state_path), \
             patch.object(aj, "_send_photo",
                          return_value=hero_receipt
                          or {"ok": True}), \
             patch.object(aj, "_send_message",
                          side_effect=fake_send):
            rc = aj.run_scan(send=True)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        return rc, state, calls["i"]

    def test_transient_failure_keeps_state_clean(self):
        rc, state, _calls = self._run(
            {"ok": False, "message_id": None,
             "error_class": "retry", "error": "network: URLError"})
        self.assertEqual(rc, 1)
        self.assertEqual(state, {})   # retried next hour by the cron

    def test_permanent_failure_is_terminal_with_reason(self):
        rc, state, _calls = self._run(
            {"ok": False, "message_id": None,
             "error_class": "permanent",
             "error": "403 Forbidden: bot kicked"})
        self.assertEqual(rc, 2)
        entry = state["2026-09-09"]
        self.assertFalse(entry["posted"])
        self.assertTrue(entry["terminal"])
        self.assertIn("bot kicked", entry["error"])
        fire, _ = aj.should_fire(WED_6AM, state=state)
        self.assertFalse(fire)        # no pointless hourly retries

    def test_partial_ok_marks_posted_with_failure_record(self):
        rc, state, calls = self._run(
            [{"ok": True, "message_id": 11, "error_class": "",
              "error": ""},
             {"ok": False, "message_id": None,
              "error_class": "retry", "error": "network: timeout"}],
            n_items=200)              # forces multiple split blocks
        self.assertGreater(calls, 1)  # at least 2 blocks were sent
        self.assertEqual(rc, 0)
        entry = state["2026-09-09"]
        self.assertTrue(entry["posted"])
        self.assertGreaterEqual(entry["failed_blocks"], 1)
        self.assertEqual(entry["message_ids"], [11])


class TestCliWiring(unittest.TestCase):
    def test_cmd_scan_flag_wires_run_scan(self):
        # the CLI lives BESIDE the tracker (workspace root) both
        # locally and in the VPS container — put that dir on sys.path
        sys.path.insert(0, str(_PROJECT.parent))
        import grocery_price_cli as cli
        called = {}
        with patch("core.aldi_specials.run_scan",
                   side_effect=lambda **kw:
                   called.update(kw) or 0):
            rc = cli._cmd_aldi_specials(
                type("A", (), {"force": False, "date": None,
                               "no_telegram": False})())
        self.assertEqual(rc, 0)
        self.assertEqual(called, {"force": False, "date_iso": None,
                                  "send": True})


if __name__ == "__main__":
    unittest.main()
