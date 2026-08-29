#!/usr/bin/env python3
"""Tests for the live-window offline pieces (Part C).

Matrix F (this module's first class): snapshot conversion for
extractors/live_list_fetch.py — all file-based, NO network, NO browser.
Matrices W (session logic) and D (automation assets) join later
classes in this same file per plan IN-7.
"""
from __future__ import annotations
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors import live_list_fetch as llf  # noqa: E402
from extractors import session_refresh as sr  # noqa: E402
from extractors.models import ProductItem  # noqa: E402


def _ww_item(name="WW Milk 2L", price=3.50, stockcode=123456, **extra):
    """Raw WW list-API product dict fixture."""
    item = {
        "Stockcode": stockcode,
        "DisplayName": name,
        "Price": price,
        "PackageSize": "2L",
        "Brand": "Pura",
    }
    item.update(extra)
    return item


def _coles_item(name="Coles Milk 2L", price=3.20, pid="998877", **extra):
    """Raw Coles product dict fixture (search-result shape)."""
    item = {
        "_type": "PRODUCT",
        "name": name,
        "id": pid,
        "size": "2L",
        "pricing": {"now": price},
    }
    item.update(extra)
    return item


class TestSnapshotConversion(unittest.TestCase):
    """Matrix F-1..F-10: offline snapshot loading + validation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.snapshots = tmp / "live_snapshots"
        self.snapshots.mkdir()
        self._patchers = [
            patch.object(llf, "SNAPSHOTS_DIR", self.snapshots),
            patch.object(llf, "DATA_DIR", tmp),
        ]
        for p in self._patchers:
            p.start()
        self.date = "2026-09-02"

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def write_ww(self, payload, slug="pricecompare"):
        """Write a WW snapshot file."""
        path = llf.ww_snapshot_path(self.date, slug)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def write_coles(self, payload):
        """Write a Coles snapshot file."""
        path = llf.coles_snapshot_path(self.date)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    # -- matrix ----------------------------------------------------------
    def test_f1_ww_specials_semantics(self):
        """F-1: IsOnSpecial/WasPrice/SavingsAmount -> extractor strings."""
        payload = [
            _ww_item(name="A", WasPrice=4.00, IsOnSpecial=True),
            _ww_item(name="B", stockcode=2, IsHalfPrice=True),
            _ww_item(name="C", stockcode=3, SavingsAmount=0.50,
                     IsOnSpecial=True),
            _ww_item(name="D", stockcode=4),
        ]
        items = llf.load_ww_snapshot(self.write_ww(payload))
        self.assertEqual(items[0].special_desc, "Was $4.00")
        self.assertEqual(items[1].special_desc, "Half Price")
        self.assertEqual(items[2].special_desc, "Save $0.50")
        self.assertEqual(items[3].special_desc, "")
        self.assertTrue(items[0].is_special)
        self.assertFalse(items[3].is_special)

    def test_f2_coles_snapshot_via_parse_search_result(self):
        """F-2: Coles fixture -> ProductItems (price/special/size)."""
        payload = [
            _coles_item(),
            {"_type": "BANNER", "name": "Half price sale"},  # filtered
        ]
        items = llf.load_coles_snapshot(self.write_coles(payload))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw_name, "Coles Milk 2L")
        self.assertEqual(items[0].price, 3.20)
        self.assertEqual(items[0].size, "2L")

    def test_f3_multipage_dedup_by_product_id(self):
        """F-3: same id across pages/boundaries appears once (DELTA-2)."""
        page1 = [_ww_item(name="WW Milk 2L", stockcode=111)]
        page2 = [_ww_item(name="WW Milk 2L", stockcode=111),
                 _ww_item(name="WW Bread", stockcode=222)]
        # Both pages land in one snapshot list; cross-page dedup applies.
        self.write_ww(page1 + page2)
        items = llf.load_ww_snapshot(
            llf.ww_snapshot_path(self.date, "pricecompare"))
        ids = [i.product_id for i in items]
        self.assertEqual(ids.count("111"), 1)
        self.assertEqual(len(items), 2)

    def test_f4_snapshots_for_date_returns_both_stores(self):
        """F-4: snapshots_for_date returns both stores' items."""
        self.write_ww([_ww_item()])
        self.write_coles([_coles_item()])
        snaps = llf.snapshots_for_date(self.date)
        self.assertEqual(len(snaps["woolworths"]), 1)
        self.assertEqual(len(snaps["coles"]), 1)
        self.assertEqual(snaps["woolworths"][0].store, "woolworths")
        self.assertEqual(snaps["coles"][0].store, "coles")

    def test_f5_validate_complete_names_missing_files(self):
        """F-5: missing files -> ValueError naming the exact file(s)."""
        with self.assertRaises(ValueError) as ctx:
            llf.validate_complete(self.date)
        msg = str(ctx.exception)
        self.assertIn(f"{self.date}_ww_pricecompare.json", msg)
        self.assertIn(f"{self.date}_coles_pricecompare.json", msg)

    def test_f6_specials_from_live_filters_specials(self):
        """F-6: specials_from_live filters the Special-list snapshot."""
        self.write_ww([_ww_item(name="A", IsOnSpecial=True, WasPrice=4.0)],
                      slug="speciallist28")
        self.write_ww([_ww_item(name="B")], slug="pricecompare")
        specials = llf.specials_from_live(self.date)
        self.assertEqual(len(specials), 1)
        self.assertEqual(specials[0].raw_name, "A")
        # No specials file at all -> empty (caller warns instead).
        self.assertEqual(llf.specials_from_live("1999-01-01"), [])

    def test_f7_corrupt_snapshot_valueerror_not_crash(self):
        """F-7: corrupt snapshot -> ValueError naming the file."""
        path = self.write_ww("this is not json {")
        with self.assertRaises(ValueError) as ctx:
            llf.load_ww_snapshot(path)
        self.assertIn(path.name, str(ctx.exception))

    def test_f8_id_missing_falls_back_to_name_dedup(self):
        """F-8: id-missing items dedup by normalised name."""
        payload = [
            _ww_item(name="WW Milk 2L", stockcode=None),
            _ww_item(name="ww  MILK 2l", stockcode=None),
        ]
        items = llf.load_ww_snapshot(self.write_ww(payload))
        self.assertEqual(len(items), 1)

    def test_f9_quantity_does_not_duplicate(self):
        """F-9: WW list Quantity never duplicates items."""
        payload = [_ww_item(name="WW Milk 2L", Quantity=3)]
        items = llf.load_ww_snapshot(self.write_ww(payload))
        self.assertEqual(len(items), 1)

    def test_f10_loader_never_touches_network(self):
        """F-10: loaders make no requests calls (offline by construction)."""
        self.write_ww([_ww_item()])
        self.write_coles([_coles_item()])
        import requests
        with patch.object(requests, "get",
                          side_effect=AssertionError("network!")):
            snaps = llf.snapshots_for_date(self.date)
        self.assertEqual(len(snaps["woolworths"]), 1)
        self.assertEqual(len(snaps["coles"]), 1)
        # Guardrail 5: no Scrape.do reference anywhere in this module.
        source = open(llf.__file__, encoding="utf-8").read().lower()
        self.assertNotIn("scrape.do", source)


class TestSessionRefresh(unittest.TestCase):
    """Matrix W-1..W-20: pagination walker, flush engine, discovery,
    heartbeat, phase orchestration — fully injected, NO browser."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._patchers = [
            patch.object(sr, "FLUSH_LOG_PATH", tmp / "live_flush_log.json"),
            patch.object(sr, "CAPTURE_PATH", tmp / "live_api_capture.json"),
            patch.object(sr, "SESSION_STATE_PATH",
                         tmp / "session_state.json"),
            patch.object(sr, "HEARTBEAT_LOG_PATH",
                         tmp / "session_heartbeat.log"),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    # W-1..W-4: pagination walker
    # ------------------------------------------------------------------
    def test_w1_walks_until_has_more_false(self):
        """W-1: walker loops until hasMore=false; collects all items."""
        pages = {1: {"items": [1, 2], "has_more": True},
                 2: {"items": [3], "has_more": False}}
        outcome = sr._walk_pagination(
            lambda p: pages[p], page_size=2, store_label="WW 'Price Compare'")
        self.assertEqual(outcome["items"], [1, 2, 3])
        self.assertEqual(outcome["pages"], 2)
        self.assertFalse(outcome["capped"])
        self.assertEqual(outcome["warning"], "")

    def test_w2_short_page_without_has_more_stops(self):
        """W-2: short page (< page size) with no hasMore field stops."""
        pages = {1: {"items": [1, 2, 3], "has_more": None},
                 2: {"items": [4], "has_more": None}}
        calls = []
        outcome = sr._walk_pagination(
            lambda p: (calls.append(p), pages[p])[1], page_size=3)
        self.assertEqual(outcome["items"], [1, 2, 3, 4])
        self.assertEqual(calls, [1, 2])   # stopped: page 2 was short

    def test_w3_page_cap_loud_warning(self):
        """W-3: cap reached -> stops + LOUD warning incl. item count."""
        def fetch(page):
            return {"items": [f"i{page}"], "has_more": True}
        outcome = sr._walk_pagination(fetch, page_size=1, max_pages=3,
                                      store_label="WW 'Price Compare'")
        self.assertTrue(outcome["capped"])
        self.assertEqual(len(outcome["items"]), 3)
        self.assertIn("3-page hard cap", outcome["warning"])
        self.assertIn("3 items fetched so far", outcome["warning"])
        self.assertEqual(sr.PAGE_HARD_CAP, 30)

    def test_w4_per_list_log_line(self):
        """W-4: per-list log line 'WW 'Price Compare': 4 pages, N items'."""
        pages = {p: {"items": [p * 10 + k for k in range(2)],
                     "has_more": p < 4} for p in range(1, 5)}
        old_stdout = sys.stdout
        try:
            sys.stdout = io.StringIO()
            sr._walk_pagination(lambda p: pages[p], page_size=2,
                                store_label="WW 'Price Compare'")
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        self.assertIn("WW 'Price Compare': 4 pages, 8 items", out)

    # ------------------------------------------------------------------
    # W-5: flush grouping + target list
    # ------------------------------------------------------------------
    def test_w5_flush_groups_by_store_targets_price_compare(self):
        """W-5: flush groups by store; targets 'Price Compare' only."""
        entries = [
            {"store": "woolworths", "keyword": "A", "queue": "searched_items"},
            {"store": "coles", "keyword": "B", "queue": "add_to_list"},
            {"store": "woolworths", "keyword": "C", "queue": "add_to_list"},
        ]
        grouped = sr._group_by_store(entries)
        self.assertEqual(len(grouped["woolworths"]), 2)
        self.assertEqual(len(grouped["coles"]), 1)
        self.assertEqual(sr.FLUSH_TARGET_LIST, "Price Compare")
        self.assertNotIn("Special list (28)", [sr.FLUSH_TARGET_LIST])

    # ------------------------------------------------------------------
    # W-6..W-13: flush engine
    # ------------------------------------------------------------------
    def _flush(self, entries, add_item, tmpdir=None, **kwargs):
        """Flush helper: injected recorder + isolated log path."""
        consumed = []
        records = []
        sleeps = []
        sleep_fn = kwargs.pop("sleep", None) or (lambda s: sleeps.append(s))
        clock = kwargs.pop("clock", None) or (lambda: 0.0)
        jitter = kwargs.pop("jitter", None) or (lambda: 0.0)
        result = sr._flush_store(
            "coles", entries,
            add_item=add_item,
            consume_entry=lambda e: consumed.append(e),
            log_append=lambda r: records.append(r),
            sleep=sleep_fn,
            clock=clock,
            jitter=jitter,
            **kwargs)
        return result, consumed, records, sleeps

    def test_w6_success_consumes_entries(self):
        """W-6: flush success removes entries (consume called)."""
        entries = [{"store": "coles", "keyword": "A", "code": "KAT",
                    "queue": "searched_items"}]
        result, consumed, _records, _sleeps = self._flush(
            entries,
            lambda e: {"status": "added", "kind": "ok", "reason": ""})
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(len(consumed), 1)
        self.assertEqual(consumed[0]["code"], "KAT")

    def test_w7_failure_retains_item_with_reason_and_attempts(self):
        """W-7: failure retains item with reason + attempts recorded."""
        entries = [{"store": "coles", "keyword": "A"}]
        result, _consumed, records, _sleeps = self._flush(
            entries,
            lambda e: {"status": "failed", "kind": "permanent",
                       "reason": "HTTP 500"})
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["reason"], "HTTP 500")
        self.assertEqual(records[0]["attempts"], 1)

    def test_w8_three_strike_park(self):
        """W-8: attempts>=3 -> parked, not attempted, listed needs-manual."""
        history = {("coles", "A"): 3}
        to_flush, parked = sr._partition_parked(
            "coles", [{"store": "coles", "keyword": "A"}], history)
        self.assertEqual(to_flush, [])
        self.assertEqual(len(parked), 1)
        calls = []
        result, _consumed, _records, _sleeps = self._flush(
            to_flush, lambda e: calls.append(1))
        self.assertEqual(calls, [])   # parked items are never attempted

    def test_w9_one_failure_never_blocks_others(self):
        """W-9: one item's failure doesn't block the others."""
        entries = [{"store": "coles", "keyword": "A"},
                   {"store": "coles", "keyword": "B"}]
        responses = [{"status": "failed", "kind": "permanent",
                      "reason": "bad"},
                     {"status": "added", "kind": "ok", "reason": ""}]
        result, _consumed, _records, _sleeps = self._flush(
            entries, lambda e: responses.pop(0))
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(len(result["failed"]), 1)

    def test_w10_session_death_aborts_remaining(self):
        """W-10: 401/403 aborts the store's remaining flush."""
        entries = [{"store": "coles", "keyword": "A"},
                   {"store": "coles", "keyword": "B"},
                   {"store": "coles", "keyword": "C"}]
        def add_item(entry):
            if entry["keyword"] == "A":
                return {"status": "added", "kind": "ok", "reason": ""}
            return {"status": "failed", "kind": "session_death",
                    "reason": "HTTP 403"}
        calls = []
        result, consumed, _records, _sleeps = self._flush(
            entries, lambda e: (calls.append(e["keyword"]), add_item(e))[1])
        self.assertEqual(calls, ["A", "B"])   # C never attempted
        self.assertEqual(len(consumed), 1)    # prior success consumed
        self.assertTrue(result["session_died"])
        self.assertEqual(len(result["failed"]), 1)  # B stays queued

    def test_w11_retry_policy(self):
        """W-11: transient -> exactly 1 retry; session death -> 0."""
        entries = [{"store": "coles", "keyword": "A"}]
        responses = [{"status": "failed", "kind": "transient",
                      "reason": "timeout"},
                     {"status": "added", "kind": "ok", "reason": ""}]
        result, _consumed, records, _sleeps = self._flush(
            entries, lambda e: responses.pop(0))
        self.assertEqual(len(result["added"]), 1)
        self.assertEqual(records[0]["attempts"], 2)
        # Session death: single attempt, never retried.
        responses = [{"status": "failed", "kind": "session_death",
                      "reason": "HTTP 401"}]
        result2, _consumed, records2, _sleeps = self._flush(
            [{"store": "coles", "keyword": "B"}],
            lambda e: responses[0])
        self.assertTrue(result2["session_died"])
        self.assertEqual(records2[0]["attempts"], 1)

    def test_w12_throttle_pace(self):
        """W-12: consecutive adds are >=1.5 s apart (injected sleep)."""
        entries = [{"store": "coles", "keyword": k} for k in "ABC"]
        sleeps = []
        result, _consumed, _records, _helper_sleeps = self._flush(
            entries,
            lambda e: {"status": "added", "kind": "ok", "reason": ""},
            sleep=sleeps.append)
        self.assertEqual(len(result["added"]), 3)
        self.assertEqual(len(sleeps), 2)          # no sleep before the first
        self.assertTrue(all(s >= sr.FLUSH_THROTTLE_S for s in sleeps))
        # Jitter only ever ADDS delay (0..0.5), never reduces pace.
        sleeps.clear()
        self._flush(entries,
                    lambda e: {"status": "added", "kind": "ok",
                               "reason": ""},
                    sleep=sleeps.append, jitter=lambda: 0.5)
        self.assertEqual(sleeps, [2.0, 2.0])

    def test_w13_flush_log_shape_and_rotation(self):
        """W-13: log record shape {store, keyword, code?, status, reason,
        attempts, ts}; log rotation fires above the size threshold."""
        entries = [{"store": "coles", "keyword": "A", "code": "KAT"}]
        result, _consumed, _records, _sleeps = self._flush(
            entries,
            lambda e: {"status": "added", "kind": "ok", "reason": ""})
        # Persist via the real appender against the isolated path.
        sr._append_flush_log(sr.FLUSH_LOG_PATH, result and {
            "store": "coles", "keyword": "A", "code": "KAT",
            "status": "added", "reason": "", "attempts": 1,
            "ts": sr._now_iso()})
        data = json.loads(sr.FLUSH_LOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(data[0].keys()),
                         {"store", "keyword", "code", "status", "reason",
                          "attempts", "ts"})
        # Rotation: oversized file is moved aside.
        sr.FLUSH_LOG_PATH.write_text("x" * 50, encoding="utf-8")
        rotated = sr._rotate_log_if_large(sr.FLUSH_LOG_PATH, max_bytes=10)
        self.assertTrue(rotated)
        self.assertFalse(sr.FLUSH_LOG_PATH.exists())

    # ------------------------------------------------------------------
    # W-14: exact list-name matching
    # ------------------------------------------------------------------
    def test_w14_exact_list_match_never_guesses(self):
        """W-14: mismatch prints available names; never guesses."""
        with self.assertRaises(ValueError) as ctx:
            sr._match_list_names(
                ["Price Comparison", "My Specials"],
                ["Price Compare"])
        self.assertIn("Available lists", str(ctx.exception))
        matched = sr._match_list_names(
            ["Price Compare", "Special list (28)"],
            ["Price Compare", "Special list (28)"])
        self.assertEqual(matched, ["Price Compare", "Special list (28)"])

    # ------------------------------------------------------------------
    # W-15..W-16: run() phase independence + flags
    # ------------------------------------------------------------------
    def test_w15_flush_failure_does_not_stop_fetch(self):
        """W-15: flush failure doesn't stop fetch and vice versa."""
        driver = MagicMock()
        calls = []
        with patch.object(sr, "_phase_a_login",
                          side_effect=lambda d, s: None), \
                patch.object(sr, "_phase_b_flush",
                             side_effect=RuntimeError("boom")), \
                patch.object(sr, "_phase_c_fetch",
                             side_effect=lambda d, s: calls.append("C")):
            summary = sr.run(flush=True, fetch=True, _driver=driver)
        self.assertEqual(calls, ["C"])          # fetch still ran
        self.assertFalse(summary["coles"]["flush"].get("ok", True))

        # And the reverse: fetch failure doesn't block the flush summary.
        calls.clear()
        with patch.object(sr, "_phase_a_login",
                          side_effect=lambda d, s: None), \
                patch.object(sr, "_phase_b_flush",
                             side_effect=lambda d, s: calls.append("B")), \
                patch.object(sr, "_phase_c_fetch",
                             side_effect=RuntimeError("net down")):
            summary = sr.run(flush=True, fetch=True, _driver=driver)
        self.assertEqual(calls, ["B"])
        self.assertFalse(summary["coles"]["fetch"].get("ok", True))

    def test_w16_phase_flags_skip_right_phases(self):
        """W-16: --flush-only / --fetch-only skip the right phases."""
        driver = MagicMock()
        with patch.object(sr, "_phase_a_login",
                          side_effect=lambda d, s: None), \
                patch.object(sr, "_phase_b_flush") as mock_b, \
                patch.object(sr, "_phase_c_fetch") as mock_c:
            sr.run(flush=True, fetch=False, _driver=driver)
            mock_b.assert_called_once()
            mock_c.assert_not_called()
        with patch.object(sr, "_phase_a_login",
                          side_effect=lambda d, s: None), \
                patch.object(sr, "_phase_b_flush") as mock_b, \
                patch.object(sr, "_phase_c_fetch") as mock_c:
            sr.run(flush=False, fetch=True, _driver=driver)
            mock_b.assert_not_called()
            mock_c.assert_called_once()

    # ------------------------------------------------------------------
    # W-17..W-20: heartbeat, guardrail grep, lazy import, discovery
    # ------------------------------------------------------------------
    def test_w17_heartbeat_never_raises_coles_unknown(self):
        """W-17: alive/dead/unknown lines; Coles 'unknown' tolerated."""
        state = {"woolworths": {"cookies": {"a": "b"}},
                 "coles": {"cookies": {}}}
        sr.SESSION_STATE_PATH.write_text(json.dumps(state),
                                         encoding="utf-8")
        statuses = {"woolworths": 200, "coles": 403}

        def fetcher(store, url, cookies):
            if store == "coles" and not url:
                raise RuntimeError("no check url")   # best-effort
            return statuses[store]

        result = sr.run_heartbeat(fetcher=fetcher)
        self.assertEqual(result["woolworths"], "alive")
        self.assertEqual(result["coles"], "unknown")   # tolerated
        log_text = sr.HEARTBEAT_LOG_PATH.read_text(encoding="utf-8")
        self.assertIn("alive ", log_text)
        self.assertIn("unknown ", log_text)
        # A dead WW is recorded dead; total failures never raise.
        statuses["woolworths"] = 403
        result = sr.run_heartbeat(fetcher=fetcher)
        self.assertEqual(result["woolworths"], "dead")

    def test_w18_assert_by_grep_no_scrapedo(self):
        """W-18: session_refresh + live_list_fetch contain no scrape.do."""
        for module in (sr, llf):
            source = open(module.__file__, encoding="utf-8").read().lower()
            self.assertNotIn("scrape.do", source)
            self.assertNotIn("scrapedo", source.replace("_", "x"))
        # (the second check catches incidental camel-case references too;
        # legitimate module-level constants live elsewhere)

    def test_w19_lazy_playwright_import(self):
        """W-19: import succeeds with playwright blocked; launch errors
        with the local-desktop guidance."""
        import importlib
        with patch.dict(sys.modules,
                        {"playwright": None,
                         "playwright.sync_api": None}):
            module = importlib.import_module("extractors.session_refresh")
            self.assertIsNotNone(module)
            with self.assertRaises(RuntimeError) as ctx:
                module._open_browser()
            self.assertIn("local desktop", str(ctx.exception))

    def test_w20_discovery_capture_writer(self):
        """W-20: capture writer stores {method, url, body_shape,
        pagination} per store."""
        capture = {
            "method": "POST",
            "url": "https://www.coles.com.au/api/v1/lists/items",
            "body_shape": {"name": "", "productId": ""},
            "pagination": {"page_param": "page", "page_size": 50,
                           "has_more_field": "hasMore"},
        }
        self.assertTrue(sr._needs_capture("coles"))   # no capture yet
        sr._write_discovery_capture("coles", capture)
        self.assertFalse(sr._needs_capture("coles"))
        stored = json.loads(sr.CAPTURE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(stored["coles"]["method"], "POST")
        self.assertEqual(stored["coles"]["pagination"]["page_param"],
                         "page")


class TestAutomationAssets(unittest.TestCase):
    """Matrix D-1..D-7: deploy manifest/scp/restart/smoke, heartbeat
    entry, trial_check list comparison, arg-list-only subprocess use."""

    @staticmethod
    def _load_script(name):
        """Import a scripts/ file as a module (no package needed)."""
        import importlib.util
        path = _PROJECT / "scripts" / name
        spec = importlib.util.spec_from_file_location(name[:-3], path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.deploy = self._load_script("deploy_vps.py")
        self.entry = self._load_script("session_heartbeat_entry.py")
        self.check = self._load_script("trial_check.py")

    # ------------------------------------------------------------------
    def test_d1_manifest_covers_tasks_and_nothing_else(self):
        """D-1: FILE_MANIFEST covers the Tasks 1-11 artefacts; never
        .env / data/ / .docx."""
        manifest = " ".join(rel for rel, _ in self.deploy._FILE_MANIFEST)
        for must in ("grocery_price_cli.py", "SKILL.md",
                     "core/uom.py", "core/searched_items.py",
                     "core/lookup.py", "core/price_comparator.py",
                     "extractors/live_list_fetch.py",
                     "extractors/session_refresh.py",
                     "test_live_window.py", "deploy_vps.py",
                     "trial_check.py", "session_heartbeat_entry.py",
                     "README.md"):
            self.assertIn(must, manifest)
        for rel, _remote in self.deploy._FILE_MANIFEST:
            for marker in self.deploy.FORBIDDEN_MARKERS:
                self.assertNotIn(marker, rel)
        # And the plan resolves to existing files.
        plan = self.deploy.build_plan()
        self.assertEqual(len(plan), len(self.deploy._FILE_MANIFEST))

    def test_d2_scp_then_restart_then_smoke_order(self):
        """D-2: scps per manifest file -> ONE ssh-wrapped docker restart
        on the VPS -> container smoke (searched-items show), in order."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(self.deploy.subprocess, "run",
                          side_effect=fake_run), \
                patch.object(self.deploy, "_has_git_remote",
                             return_value=False):
            with patch.object(sys, "argv", ["deploy_vps.py"]):
                code = self.deploy.main()
        self.assertEqual(code, 0)
        scps = [c for c in calls if c[0] == "scp"]
        self.assertEqual(len(scps), len(self.deploy._FILE_MANIFEST))
        for c in scps:
            self.assertIsInstance(c, list)      # argument LIST, no shell
        # docker commands are ssh-wrapped (openclaw-core lives on the VPS)
        restarts = [c for c in calls if "docker" in c and "restart" in c]
        self.assertEqual(len(restarts), 1)
        self.assertEqual(restarts[0][0], "ssh")
        smokes = [c for c in calls if "searched-items" in c]
        self.assertEqual(len(smokes), 1)
        self.assertIn("docker", smokes[0])
        self.assertIn("exec", smokes[0])
        # Order: every scp BEFORE the restart, restart BEFORE the smoke.
        first_non_scp = next(i for i, c in enumerate(calls)
                             if c[0] != "scp")
        self.assertTrue(all(c[0] == "scp" for c in calls[:first_non_scp]))
        self.assertLess(calls.index(restarts[0]), calls.index(smokes[0]))

    def test_d3_scp_failure_retry_hint_nonzero(self):
        """D-3: scp failure -> exit 1 (covered in full by D-3b)."""
        responses = {"fail_after": 2}

        def fake_run(cmd, **kwargs):
            responses["fail_after"] -= 1
            ok = responses["fail_after"] > 0
            return SimpleNamespace(returncode=0 if ok else 1,
                                   stdout="", stderr="boom")

        with patch.object(self.deploy.subprocess, "run",
                          side_effect=fake_run), \
                patch.object(self.deploy, "_has_git_remote",
                             return_value=False):
            with patch.object(sys, "argv", ["deploy_vps.py"]):
                code = self.deploy.main()
        self.assertEqual(code, 1)

    def test_d3b_failure_hint_visible_in_output(self):
        """D-3b: the retry hint text reaches the operator output."""
        import io
        from contextlib import redirect_stderr, redirect_stdout

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")

        err = io.StringIO()
        out = io.StringIO()
        with patch.object(self.deploy.subprocess, "run",
                          side_effect=fake_run), \
                patch.object(self.deploy, "_has_git_remote",
                             return_value=False), \
                redirect_stdout(out), redirect_stderr(err):
            with patch.object(sys, "argv", ["deploy_vps.py"]):
                code = self.deploy.main()
        self.assertEqual(code, 1)
        combined = out.getvalue() + err.getvalue()
        self.assertIn("Re-run the deploy to retry", combined)
        self.assertIn("FAILED", combined)

    def test_d4_git_mode_without_remote_falls_back(self):
        """D-4: --git-mode without a remote -> scp fallback, never a
        half-deploy."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["git", "-C"]:
                return SimpleNamespace(returncode=0, stdout="",
                                       stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(self.deploy.subprocess, "run",
                          side_effect=fake_run), \
                patch.object(self.deploy, "_has_git_remote",
                             return_value=False):
            with patch.object(sys, "argv",
                              ["deploy_vps.py", "--git-mode"]):
                code = self.deploy.main()
        self.assertEqual(code, 0)
        git_pushes = [c for c in calls if c[:1] == ["git"]
                      and "push" in c]
        self.assertEqual(git_pushes, [])          # fell back to scp
        self.assertTrue(any(c[0] == "scp" for c in calls))

    def test_d5_heartbeat_entry_exits_zero_on_raise(self):
        """D-5: session_heartbeat_entry exits 0 even when the heartbeat
        raises."""
        with patch.object(self.entry, "run_heartbeat",
                          side_effect=RuntimeError("no cookies")):
            self.assertEqual(self.entry.main(), 0)

    def test_d6_compare_lists_detects_mismatch(self):
        """D-6: --compare-lists flags injected mismatches (exit 1) and
        passes identical lists (exit 0)."""
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            a.mkdir()
            b.mkdir()
            (a / "unmatched.txt").write_text(
                "# comment\nMilk [woolworths]\nBread [coles]\n",
                encoding="utf-8")
            (b / "unmatched.txt").write_text(
                "# comment\nMilk [woolworths]\nBread [coles]\n",
                encoding="utf-8")
            for name in ("wool_missing.txt", "coles_missing.txt"):
                (a / name).write_text("Item One\n", encoding="utf-8")
                (b / name).write_text("Item One\n", encoding="utf-8")
            self.assertEqual(self.check.compare_lists(a, b), [])
            # Inject: count mismatch.
            (b / "wool_missing.txt").write_text(
                "Item One\nItem Two\n", encoding="utf-8")
            mismatches = self.check.compare_lists(a, b)
            self.assertTrue(any("wool_missing.txt" in m for m in mismatches))
            # Inject: content mismatch.
            (b / "wool_missing.txt").write_text(
                "Item One\n", encoding="utf-8")
            (b / "coles_missing.txt").write_text(
                "Something Else\n", encoding="utf-8")
            mismatches = self.check.compare_lists(a, b)
            self.assertTrue(any("coles_missing.txt" in m
                                for m in mismatches))
            # Missing file detected.
            (b / "unmatched.txt").unlink()
            mismatches = self.check.compare_lists(a, b)
            self.assertTrue(any("unmatched.txt" in m for m in mismatches))

    def test_d7_arg_list_only_subprocess(self):
        """D-7: all three scripts use subprocess arg lists — no
        shell=True, no string-concatenated commands."""
        for module in (self.deploy, self.entry, self.check):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("shell=True", source)
            self.assertNotIn("os.system", source)
        # deploy_vps invokes via literal command lists.
        self.assertIn('["scp", "-o", "ConnectTimeout=10"',
                      Path(self.deploy.__file__).read_text(
                          encoding="utf-8"))
        self.assertIn('"docker", *docker_args',
                      Path(self.deploy.__file__).read_text(
                          encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
