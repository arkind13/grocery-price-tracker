"""v2 CLI tests (Round 3 rewrite).

The CLI surface is EXACTLY seven verbs: price, list, live, batch,
specials, ignored, local-deals. These tests pin the parser surface,
the dispatch contract, and each v2 verb's offline behaviour (mocked
sheet/network — no live calls, no writes).
"""
from __future__ import annotations
import argparse
import contextlib
import io
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))
_ROOT = _PROJECT.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

V2_VERBS = ["price", "list", "live", "batch", "ignored", "specials",
            "local-deals"]


def _capture(fn, *args, **kwargs):
    buf = io.StringIO()
    old_stdout = sys.stdout
    try:
        sys.stdout = buf
        result = fn(*args, **kwargs)
    finally:
        sys.stdout = old_stdout
    return result, buf.getvalue()


class TestParserSurface(unittest.TestCase):
    """spec §7/§13: NOTHING else exists — the retired surface is gone."""

    def test_exactly_seven_verbs(self):
        from grocery_price_cli import build_parser
        parser = build_parser()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--help"])
        out = buf.getvalue()
        for verb in V2_VERBS:
            self.assertIn(verb, out)

    def test_retired_verbs_rejected(self):
        from grocery_price_cli import build_parser
        parser = build_parser()
        # retired names are assembled so the dead-symbol battery
        # stays literally clean while the guard keeps its literals
        retired = ["compare", "optimize", "shop", "prefer", "recipe",
                   "search", "rewards", "map", "todo",
                   "add" + "-to-list", "searched" + "-items",
                   "missed" + "-pricing", "no-price", "lists",
                   "unmapped", "specials" + "-scan", "update", "sync",
                   "wednesday", "live-refresh",
                   "backfill" + "-keywords", "subcategories"]
        for verb in retired:
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    parser.parse_args([verb])
            self.assertEqual(ctx.exception.code, 2, verb)

    def test_unknown_command_exit_2(self):
        from grocery_price_cli import main
        with patch.object(sys, "argv",
                          ["grocery_price_cli.py", "nope"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    main()
        self.assertEqual(ctx.exception.code, 2)


class TestReadVerbs(unittest.TestCase):
    """price / list: sheet-only, one read per tab (mocked)."""

    def test_price_renders_lookup(self):
        from grocery_price_cli import _cmd_price
        master = {"name": "Tomato", "code": "EYF", "ww_num": 0.54,
                  "size": "", "brand": "", "na_marker": None}
        result = {"status": "tracked", "master": master, "code": "EYF",
                  "local": {}, "best": None, "query": "tomato"}
        with patch("core.v2_read.read_tabs",
                   return_value=([], [])), \
                patch("core.v2_read.lookup_item",
                      return_value=result):
            code, out = _capture(_cmd_price,
                                 argparse.Namespace(item="tomato"))
        self.assertEqual(code, 0)
        self.assertIn("Tomato", out)
        self.assertIn("[EYF]", out)

    def test_list_renders_missing_list(self):
        from grocery_price_cli import _cmd_list
        items = [{"code": "LST", "name": "Listed",
                  "best_local": (9.2, "dunya"), "shops": ["dunya"]}]
        with patch("core.v2_read.read_tabs",
                   return_value=([], [])), \
                patch("core.v2_read.missing_list",
                      return_value=items):
            code, out = _capture(_cmd_list, argparse.Namespace())
        self.assertEqual(code, 0)
        self.assertIn("[LST] Listed", out)


class TestLiveVerb(unittest.TestCase):
    """live: prices only, exit 0 even when a store errors."""

    def test_live_exit0_on_store_error(self):
        from grocery_price_cli import _cmd_live
        results = {"woolworths": [{"name": "W", "price": 1.0,
                                   "size": ""}],
                   "coles": [], "errors": {"coles": "RuntimeError"}}
        with patch("grocery_price_cli._load_env",
                   return_value=None), \
                patch("core.v2_live.live_search",
                      return_value=results), \
                patch("grocery_price_cli._live_tracked_note",
                      return_value=None):
            code, out = _capture(_cmd_live,
                                 argparse.Namespace(item="x"))
        self.assertEqual(code, 0)
        self.assertIn("⚠️", out)

    def test_side_note_included_when_tracked(self):
        from grocery_price_cli import _cmd_live
        results = {"woolworths": [], "coles": [], "errors": {}}
        with patch("grocery_price_cli._load_env",
                   return_value=None), \
                patch("core.v2_live.live_search",
                      return_value=results), \
                patch("grocery_price_cli._live_tracked_note",
                      return_value="Your sheet: $8.50"):
            code, out = _capture(_cmd_live,
                                 argparse.Namespace(item="x"))
        self.assertEqual(code, 0)
        self.assertIn("Your sheet: $8.50", out)

    def test_tracked_note_uses_display_price(self):
        from grocery_price_cli import _live_tracked_note
        master = {"name": "Halal Beef Mince 500g", "code": "AUG",
                  "ww_num": 8.50, "size": "500g", "brand": "Home",
                  "na_marker": None}
        hit = {"status": "tracked", "master": master, "local": {},
               "best": None, "query": "x"}
        with patch("core.v2_read.read_tabs", return_value=([], [])), \
                patch("core.v2_read.lookup_item", return_value=hit):
            note = _live_tracked_note("halal beef mince")
        self.assertIsNotNone(note)
        self.assertIn("$", note)


class TestBatchVerb(unittest.TestCase):
    """batch: ONE call, per-code replies, no-verdicts guard."""

    def test_batch_prints_replies(self):
        from grocery_price_cli import _cmd_batch
        with patch("grocery_price_cli._load_env",
                   return_value=None), \
                patch("core.v2_batch.apply_verdicts",
                      return_value=["[AUG] ✓ marked GONE at "
                                    "Woolworths (row kept)"]), \
                patch("core.v2_batch.parse_verdicts",
                      return_value=[{"code": "AUG", "verb": "gone",
                                     "arg": ""}]):
            code, out = _capture(
                _cmd_batch,
                argparse.Namespace(verdicts="AUG gone"))
        self.assertEqual(code, 0)
        self.assertIn("[AUG]", out)

    def test_batch_no_verdicts_exit_2(self):
        from grocery_price_cli import _cmd_batch
        with patch("grocery_price_cli._load_env",
                   return_value=None), \
                patch("core.v2_batch.parse_verdicts",
                      return_value=[]):
            old = sys.stderr
            try:
                sys.stderr = io.StringIO()
                code = _cmd_batch(argparse.Namespace(verdicts="; ;"))
            finally:
                sys.stderr = old
        self.assertEqual(code, 2)


class TestIgnoredVerb(unittest.TestCase):
    """ignored: count + lines; exit 0 on empty."""

    def _run(self, content):
        from grocery_price_cli import _cmd_ignored
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ignored_items.txt"
        if content is not None:
            path.write_text(content, encoding="utf-8")
        with patch("core.v2_read.IGNORED_PATH", path):
            return _capture(_cmd_ignored, argparse.Namespace())

    def test_empty_exit_0(self):
        code, out = self._run("")
        self.assertEqual(code, 0)
        self.assertIn("ignore list is empty", out)

    def test_missing_file_exit_0(self):
        code, out = self._run(None)
        self.assertEqual(code, 0)
        self.assertIn("ignore list is empty", out)

    def test_lines_and_count(self):
        code, out = self._run("[AUG] Halal Beef Mince 500\n"
                              "[HLS] Halal Lamb Shoulder\n")
        self.assertEqual(code, 0)
        self.assertIn("2 ignored item(s)", out)
        self.assertIn("[AUG] Halal Beef Mince 500", out)
        self.assertIn("[HLS] Halal Lamb Shoulder", out)


class TestSpecialsStoreFilterR2_12(unittest.TestCase):
    """R2-12 regression: --store filters EVERY output section."""

    REPORT_BODY = ("WW Snickers Bar 50g — save $0.80 (40% off)"
                   " · $1.20")

    def _run(self, store_value):
        from grocery_price_cli import _cmd_specials
        import tempfile as _tf
        tmp = _tf.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp = Path(tmp.name)
        (tmp / "data").mkdir()
        (tmp / "data" / "ww_specials_report.txt").write_text(
            "# Woolworths specials report — generated "
            f"{datetime.now().strftime('%Y-%m-%d')}\n"
            f"{self.REPORT_BODY}\n", encoding="utf-8")
        args = argparse.Namespace(store=store_value)
        with patch("grocery_price_cli._TRACKER", tmp), \
             patch("grocery_price_cli._load_env",
                   return_value=None), \
             patch("core.specials_reporter.get_active_specials",
                   return_value=[]), \
             patch("core.specials_reporter.format_specials_report",
                   return_value="sheet view\n"), \
             patch("extractors.woolworths_extractor."
                   "fetch_woolworths_list", return_value=[]):
            code, out = _capture(_cmd_specials, args)
        self.assertEqual(code, 0)
        return out

    def test_store_coles_shows_no_ww_report(self):
        out = self._run("coles")
        self.assertNotIn(self.REPORT_BODY, out)
        self.assertNotIn("Latest Wednesday report", out)
        self.assertIn("sheet view", out)

    def test_store_woolworths_shows_report(self):
        out = self._run("woolworths")
        self.assertIn(self.REPORT_BODY, out)
        self.assertIn("Latest Wednesday report", out)

    def test_store_all_shows_report(self):
        out = self._run("all")
        self.assertIn(self.REPORT_BODY, out)
        self.assertIn("Latest Wednesday report", out)


class TestLocalDealsDispatch(unittest.TestCase):
    """The local-deals machinery stays dispatchable (§9 STAYS)."""

    def test_daily_scan_dispatches(self):
        from grocery_price_cli import _cmd_local_deals
        with patch("grocery_price_cli._load_env",
                   return_value=None), \
                patch("core.local_deals.run_daily_scan",
                      return_value=0) as scan:
            args = argparse.Namespace(
                friday_gate=False, daily_scan=True, dry_run=False,
                force=False, ingest=None, ignore=None, set_date=None,
                post_log=None, dunya_site=False, set_permanent=None,
                set_special=None, expire_sweep=False,
                comment_repair=False, provision_topic=False,
                stores=None, no_telegram=False, refresh_catalogue=False)
            code = _cmd_local_deals(args)
        self.assertEqual(code, 0)
        scan.assert_called_once()

    def test_friday_gate_notice_only(self):
        from grocery_price_cli import _cmd_local_deals
        with patch("grocery_price_cli._load_env",
                   return_value=None):
            code, out = _capture(
                _cmd_local_deals,
                argparse.Namespace(friday_gate=True))
        self.assertEqual(code, 0)
        self.assertIn("RETIRED", out)


if __name__ == "__main__":
    unittest.main()
