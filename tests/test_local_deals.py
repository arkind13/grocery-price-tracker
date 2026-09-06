"""Offline tests for core/local_deals (spec §14.4-14.11, §14.17,
§9 S31/S32). FakeWorksheet/FakeSpreadsheet + mocked transports.
Zero skips. (test_tier3_butchery_reader_domain_only lives in
tests/test_halal.py — core.halal is a Part-2 dependency.)
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from core import local_deals as ld
from extractors.fb_flyer_fetch import FetchUnavailable


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeWorksheet:
    """gspread Worksheet stand-in recording clear/freeze/update."""

    def __init__(self, title="Local_Deals"):
        self.title = title
        self.rows: list[list] = []
        self.frozen = None
        self.updates: list[tuple] = []
        self.clear_calls = 0

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def clear(self):
        self.clear_calls += 1
        self.rows = []

    def freeze(self, rows=None, cols=None):
        self.frozen = rows

    def update(self, values=None, range_name=None, **_kw):
        self.updates.append((values, range_name))
        self.rows = values


class FakeSpreadsheet:
    """gspread Spreadsheet stand-in (worksheet + add_worksheet)."""

    def __init__(self):
        self.sheets: list[FakeWorksheet] = []

    def worksheet(self, title):
        for ws in self.sheets:
            if ws.title == title:
                return ws
        raise KeyError(title)   # gspread WorksheetNotFound analogue

    def add_worksheet(self, title, rows=100, cols=26):
        ws = FakeWorksheet(title)
        self.sheets.append(ws)
        return ws


def _deal(item="Beef Diced", store="dunya", category="butchery",
          kind="single", price=12.99, unit="kg", **extra):
    """Enriched deal row as produced by _process_store."""
    base = {"item": item, "store_key": store, "category": category,
            "price_kind": kind, "price": price, "unit": unit,
            "store_name": {"dunya": "Dunya Butchery",
                           "merjan": "Merjan Brothers Quality Meats",
                           "fruitopia": "Fruitopia Mt Druitt",
                           "abusalim": "Abu Salim Fruit Market"
                           }.get(store, store),
            "post_ref": f"{store}-p1"}
    base.update(extra)
    return base


def _master(name="Woolworths Beef Diced 1kg", size="1kg",
            wool=17.50, coles=None, sub="beef diced",
            coarse="", idx=2):
    """Products_Master row as produced by _load_master_rows."""
    return {"row_index": idx, "name": name, "category": coarse,
            "size": size, "wool_price": wool, "coles_price": coles,
            "subcategory": sub}


# ---------------------------------------------------------------------------
# 14.5 Sheet rebuild
# ---------------------------------------------------------------------------
class TestSheetRebuild(unittest.TestCase):
    """Tab rebuild: idempotent, frozen header, sections, notes."""

    def _rebuild(self, ws, deals):
        rows = ld.build_rows(deals)
        ld.rebuild_tab(ws, rows, list(deals.keys()))

    def test_rebuild_idempotent_identical_grid(self):
        """Two rebuilds with identical input -> identical grid."""
        deals = {"dunya": [_deal()]}
        ws = FakeWorksheet()
        self._rebuild(ws, deals)
        first = ws.updates[-1]
        self._rebuild(ws, deals)
        self.assertEqual(ws.updates[-1], first)
        self.assertEqual(len(ws.updates), 2)

    def test_header_row_frozen(self):
        """Row 1 frozen; header = Product + the 4 store names."""
        ws = FakeWorksheet()
        self._rebuild(ws, {"dunya": [_deal()]})
        self.assertEqual(ws.frozen, 1)
        header = ws.updates[-1][0][0]
        self.assertEqual(header[0], "Product")
        self.assertEqual(header[1:], [n for _k, n in ld.TAB_COLUMNS])

    def test_section_order_fruits_butchery_other(self):
        """Sections appear FRUITS, BUTCHERY, OTHER in grid order."""
        deals = {
            "dunya": [_deal()],                       # BUTCHERY
            "fruitopia": [
                _deal(item="Apples", store="fruitopia",
                      category="fruits", price=3.99),  # FRUITS
                _deal(item="Oreo", store="fruitopia",
                      category="other", price=2.5,
                      unit="pack"),                    # OTHER
            ],
        }
        ws = FakeWorksheet()
        self._rebuild(ws, deals)
        grid = ws.updates[-1][0]
        order = [row[0] for row in grid[1:]
                 if row[0] in ("FRUITS", "BUTCHERY", "OTHER")]
        self.assertEqual(order, ["FRUITS", "BUTCHERY", "OTHER"])

    def test_bulk_note_cell_and_shared_row_unit_price(self):
        """Bulk cell holds the note; a unit-price store keeps its
        numeric cell on the SAME canonical row."""
        deals = {
            "abusalim": [_deal(item="Potatoes", store="abusalim",
                               category="fruits",
                               kind="bulk_pack", price=2.99,
                               unit="pack", bulk_size="5kg")],
            "fruitopia": [_deal(item="Potatoes", store="fruitopia",
                                category="fruits", price=3.00)],
        }
        rows = ld.build_rows(deals)
        fruit_rows = rows.get("FRUITS") or []
        self.assertEqual(len(fruit_rows), 1)
        row = fruit_rows[0]
        self.assertIn("multi buy 5kg for $2.99", str(row))
        # fruitopia numeric on the same row (col 4 in the 7-col tab)
        self.assertEqual(row[4], 3.00)

    def test_out_of_domain_items_recorded_under_other(self):
        """Out-of-domain items are recorded (never dropped) under
        OTHER, standalone."""
        deals = {"fruitopia": [_deal(item="Oreo", store="fruitopia",
                                     category="other", price=2.5,
                                     unit="pack")]}
        rows = ld.build_rows(deals)
        self.assertIn("OTHER", rows)
        self.assertNotIn("FRUITS", rows)

    def test_products_master_never_written_fake_assert(self):
        """No write path touches the master sheet fake."""
        ws = FakeWorksheet(title="Products_Master")
        writes: list = []
        master = ld._load_master_rows(ws)   # read only
        self.assertEqual(master, [])
        self.assertEqual(ws.updates, writes)

    def test_products_master_single_read_occurrence(self):
        """Assert-by-grep: the master sheet name occurs exactly once
        in core/local_deals.py (inside the read helper)."""
        source = Path(ld.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("Products_Master"), 1)


# ---------------------------------------------------------------------------
# 14.6 Detection matrix
# ---------------------------------------------------------------------------
class TestDetection(unittest.TestCase):
    """>20% detection, baselines, unit gate, variety, extra stop."""

    def _detect(self, deals, masters, sites=None):
        return ld.match_and_detect(deals, masters, sites or {})

    def test_pct_20_0_no_alert(self):
        """pct exactly 20.0 -> NO alert (strictly greater rule)."""
        results = self._detect([_deal(price=12.00)],
                               [_master(wool=15.00)])
        self.assertIsNotNone(results[0].pct)
        self.assertEqual(results[0].pct, pytest.approx(20.0))
        self.assertFalse(results[0].alert)

    def test_pct_20_1_alerts(self):
        """pct 20.1 -> alert."""
        results = self._detect(
            [_deal(price=11.99)],
            [_master(name="Woolworths Beef Diced 1.0kg", wool=15.015,
                     size="1kg")])
        self.assertTrue(results[0].alert)

    def test_marker_cell_baseline_skipped(self):
        """Marker cells (N/A <date> / unavailable / GONE / blank) are
        skipped for that baseline side."""
        row = _master(wool=None, coles=None)
        row2 = dict(row)
        row2["wool_price"] = ld._numeric_price("N/A 2026-09-01")
        self.assertIsNone(ld._numeric_price("N/A 2026-09-01"))
        self.assertIsNone(ld._numeric_price("unavailable 2026-09-01"))
        self.assertIsNone(ld._numeric_price("GONE"))
        self.assertIsNone(ld._numeric_price(""))
        master = _master(wool=None, coles=None)
        results = self._detect([_deal()], [master])
        self.assertEqual(results[0].pct, None)
        self.assertFalse(results[0].alert)

    def test_multibuy_cell_counts_as_rate_baseline(self):
        """Encoded multi-buy master cells decode to their rate."""
        self.assertEqual(ld._numeric_price("multi-buy 2/$6.00"),
                         pytest.approx(3.0))

    def test_multibuy_effective_rate_deal_side(self):
        """Multibuy deal notes carry the effective per-unit rate."""
        results = self._detect(
            [_deal(item="Sausages", kind="multibuy", price=15.0,
                   unit="pack", multibuy_qty=2)], [])
        self.assertEqual(results[0].multibuy_note,
                         "multi buy 2 for $15.00 — $7.50/ea")
        self.assertFalse(results[0].alert)

    def test_unit_family_gate_blocks_cross_basis(self):
        """kg deal vs a volume master size -> unit mismatch, never
        an alert (name matches, basis does not)."""
        results = self._detect([_deal()],
                               [_master(name="Woolworths Beef Diced 2L",
                                        size="2L", wool=5.00,
                                        sub="beef diced")])
        self.assertFalse(results[0].alert)
        self.assertEqual(results[0].note, "unit mismatch")

    def test_name_drift_matched(self):
        """"Beef Diced' matches 'Woolworths Beef Diced 1kg'."""
        results = self._detect([_deal()], [_master()])
        self.assertEqual(results[0].matched_master,
                         "Woolworths Beef Diced 1kg")

    def test_unmatched_informational(self):
        """In-domain deal with no master match is informational."""
        results = self._detect([_deal(item="Camel Mince")], [])
        self.assertFalse(results[0].in_domain and results[0].alert)
        self.assertEqual(results[0].note, "no sheet match")

    def test_variety_guard_generic_vs_varietied_no_alert(self):
        """Generic flyer 'Apples' vs varietied master never alerts."""
        results = self._detect(
            [_deal(item="Apples", store="fruitopia",
                   category="fruits", price=2.00)],
            [_master(name="Woolworths Apples Royal Gala per kg",
                     size="1kg", wool=4.50, sub="apples",
                     coarse="Fruit & Veg")])
        self.assertTrue(results[0].variety_conflict)
        self.assertFalse(results[0].alert)
        self.assertEqual(results[0].note, "variety differs — verify")

    def test_variety_same_alerts_normal(self):
        """Same variety on both sides alerts normally."""
        results = self._detect(
            [_deal(item="Apples Royal Gala", store="fruitopia",
                   category="fruits", price=3.20)],
            [_master(name="Woolworths Apples Royal Gala per kg",
                     size="1kg", wool=4.50, sub="apples",
                     coarse="Fruit & Veg")])
        self.assertFalse(results[0].variety_conflict)
        self.assertTrue(results[0].alert)

    def test_extra_stop_3_items_455_recommends(self):
        """$4.55 total saving on 3 items' recommends the extra stop."""
        results = [
            _mk_alert("dunya", "Dunya Butchery", 5.00, 3.50),
            _mk_alert("dunya", "Dunya Butchery", 4.00, 2.95),
            _mk_alert("dunya", "Dunya Butchery", 5.00, 3.00),
        ]
        post1 = ld.render_post1(results, "2026-09-11")
        self.assertIn("Extra stop worth it: $4.55 total saving on "
                      "3 items", post1)

    def test_extra_stop_2_items_230_default_one_trip(self):
        """$2.30 saving (< $3.00) -> no extra-stop line."""
        results = [
            _mk_alert("dunya", "Dunya Butchery", 5.00, 4.00),
            _mk_alert("dunya", "Dunya Butchery", 4.30, 3.00),
        ]
        post1 = ld.render_post1(results, "2026-09-11")
        self.assertNotIn("Extra stop worth it", post1)


def _mk_alert(store_key, store_name, baseline, flyer,
              item="Beef Diced"):
    """Alerted unit-price MatchResult for render tests (pct derived
    from the price pair like the pipeline does)."""
    return ld.MatchResult(
        store_key=store_key, store_name=store_name,
        item_name=item, in_domain=True, alert=True,
        pct=(baseline - flyer) / baseline * 100.0,
        baseline_store="Woolworths",
        baseline_price=baseline, flyer_price=flyer, _basis="kg")


# ---------------------------------------------------------------------------
# 14.7 Report rendering
# ---------------------------------------------------------------------------
class TestReport(unittest.TestCase):
    """Post 1 / Post 2 exact formats and 4096 budget."""

    def test_post1_grouping_and_store_tags(self):
        """Store headers group the standout bullets."""
        results = [
            _mk_alert("dunya", "Dunya Butchery", 17.50, 12.99),
            _mk_alert("fruitopia", "Fruitopia Mt Druitt", 4.50, 3.20),
        ]
        post1 = ld.render_post1(results, "Fri 2026-09-11")
        self.assertIn("LOCAL STANDOUTS — Fri 2026-09-11 (Mt Druitt)",
                      post1)
        self.assertIn("DUNYA BUTCHERY", post1)
        self.assertIn("FRUITOPIA MT DRUITT", post1)
        self.assertIn("$12.99/kg  (26% < Woolworths $17.50/kg)",
                      post1)

    def test_post1_empty_message(self):
        """Empty standouts -> the brief never-silent message."""
        self.assertEqual(ld.render_post1([], "2026-09-11"),
                         "No local standouts this week")

    def test_bulk_wording_exact(self):
        """Exact note wording: tab cells + bulk report rate line."""
        deal = _deal(item="Potatoes", store="abusalim",
                     category="fruits", kind="bulk_pack", price=2.99,
                     unit="pack", bulk_size="5kg")
        rows = ld.build_rows({"abusalim": [deal]})
        # New layout: numeric specials price in the store column,
        # the multi-buy/bulk note moved to the Comments column.
        self.assertEqual(rows["FRUITS"][0][5], 2.99)
        self.assertEqual(rows["FRUITS"][0][6],
                         "[multi buy 5kg for $2.99]")
        results = ld.match_and_detect([deal], [], {})
        self.assertEqual(results[0].multibuy_note,
                         "multi buy 5kg for $2.99 — $0.60/kg")
        mb = _deal(item="Sausages", kind="multibuy", price=15.0,
                   unit="pack", multibuy_qty=2)
        rows2 = ld.build_rows({"dunya_fb": [mb]})
        self.assertEqual(rows2["BUTCHERY"][0][2], 7.5)
        self.assertEqual(rows2["BUTCHERY"][0][6],
                         "[multi buy 2 for $15.00 — $7.50/ea]")

    def test_no_prices_warn_line(self):
        """A run with one active store -> ⚠️ lines for the other
        three (mocked results carry only dunya)."""
        results = ld.match_and_detect([_deal()], [], {})
        blocks = ld.render_post2_blocks(results, "2026-09-11")
        intro = blocks[0]
        self.assertIn("⚠️ No prices found this week: Merjan Brothers "
                      "Quality Meats (no new board)", intro)

    def test_variety_verify_tag(self):
        """Suppressed variety line prints the verify tag in Post 1."""
        results = ld.match_and_detect(
            [_deal(item="Apples", store="fruitopia",
                   category="fruits", price=2.00)],
            [_master(name="Woolworths Apples Royal Gala per kg",
                     size="1kg", wool=4.50, sub="apples",
                     coarse="Fruit & Veg")], {})
        post1 = ld.render_post1(results, "2026-09-11")
        self.assertIn("variety differs — verify", post1)

    def test_post2_one_block_per_store_full_board(self):
        """Every active store gets exactly one (or split) block."""
        deals = [
            _deal(),
            _deal(item="Apples", store="fruitopia",
                  category="fruits", price=3.20),
        ]
        results = ld.match_and_detect(
            deals, [_master()], {})
        blocks = ld.render_post2_blocks(results, "2026-09-11")
        body = [b for b in blocks if not b.startswith("🛒")]
        self.assertEqual(len([b for b in body
                              if b.startswith("DUNYA")]), 1)
        self.assertEqual(len([b for b in body
                              if b.startswith("FRUITOPIA")]), 1)
        self.assertIn("1. Beef Diced — $12.99", body[0])

    def test_post2_out_of_domain_plain_unannotated_lines(self):
        """Out-of-domain items: plain lines, no notes, no pct."""
        results = ld.match_and_detect(
            [_deal(item="Oreo", store="fruitopia", category="other",
                   price=2.5, unit="pack")], [_master()], {})
        blocks = ld.render_post2_blocks(results, "2026-09-11")
        oreo_block = [b for b in blocks if "Oreo" in b][0]
        self.assertIn("1. Oreo — $2.50", oreo_block)
        self.assertNotIn("%", oreo_block)
        self.assertNotIn("multi buy", oreo_block)

    def test_40_item_block_splits_at_line_boundaries(self):
        """An oversized block splits with repeated headers and no
        broken lines."""
        results = [_mk_alert("dunya", "Dunya Butchery",
                             10.0 + i * 0.01, 5.0 + i * 0.001,
                             item=f"Premium Beef Cut Variety Number "
                                  f"{i} Marinated Extra Long Deli "
                                  f"Description Hand Trimmed")
                   for i in range(40)]
        blocks = ld.render_post2_blocks(results, "2026-09-11")
        body = [b for b in blocks if b.startswith("DUNYA")]
        self.assertGreater(len(body), 1)
        for chunk in body:
            self.assertLessEqual(len(chunk), ld.MSG_CHAR_LIMIT)
            self.assertTrue(chunk.splitlines()[0] == "DUNYA BUTCHERY")
            for line in chunk.splitlines():
                self.assertTrue(len(line) < 400)

    def test_no_message_exceeds_4096_oversized_fixture(self):
        """No rendered message exceeds the 4000-char hard cap."""
        results = ([_mk_alert("dunya", "Dunya Butchery",
                              10.0 + i * 0.001, 5.0)
                    for i in range(60)])
        blocks = ld.render_post2_blocks(results, "2026-09-11")
        self.assertTrue(all(len(b) <= ld.MSG_CHAR_LIMIT
                            for b in blocks))


# ---------------------------------------------------------------------------
# 14.8 Concurrency
# ---------------------------------------------------------------------------
class TestConcurrency(unittest.TestCase):
    """Pool size + wall-time bound (§14.8)."""

    def test_pool_max_workers_four(self):
        """run_local_deals uses ThreadPoolExecutor(max_workers=4)."""
        import concurrent.futures as cf
        seen = {}
        real_pool = cf.ThreadPoolExecutor

        class SpyPool(real_pool):
            def __init__(self, max_workers=None, **kw):
                seen["max_workers"] = max_workers
                super().__init__(max_workers=max_workers, **kw)

        with patch.object(cf, "ThreadPoolExecutor", SpyPool), \
             patch.object(ld, "_process_store",
                          side_effect=Exception("x")), \
             patch("core.sheets_client._load_env"), \
             patch("extractors.shop_site_catalogue."
                   "get_normalised_catalogue", return_value=[]):
            rc = ld.run_local_deals(dry_run=True)
        self.assertEqual(seen["max_workers"], 4)
        self.assertEqual(rc, 2)

    def test_vision_wall_time_bounded_by_slowest_post(self):
        """4 concurrent stores each sleeping 0.2s finish faster than
        the 0.8s sequential sum. """""
        import time as time_mod
        import concurrent.futures as cf

        def slow_store(store, run_dir, today):
            time_mod.sleep(0.2)
            return [_deal(store=store["key"])]

        with patch.object(ld, "_process_store", slow_store), \
             patch("core.sheets_client._load_env"), \
             patch("extractors.shop_site_catalogue."
                   "get_normalised_catalogue", return_value=[]), \
             patch.object(ld, "_load_master_rows",
                          return_value=[]), \
             patch.object(ld, "rebuild_tab"), \
             patch.object(ld, "ensure_local_deals_tab"), \
             patch("core.sheets_client.connect_spreadsheet"), \
             patch("core.sheets_client.connect_worksheet"), \
             patch.object(ld, "deliver_reports"), \
             patch.object(ld, "render_post1", return_value="x"), \
             patch.object(ld, "render_post2_blocks",
                          return_value=["x"]):
            start = time_mod.monotonic()
            rc = ld.run_local_deals(dry_run=False)
            wall = time_mod.monotonic() - start
        self.assertEqual(rc, 0)
        self.assertLess(wall, 0.8)


# ---------------------------------------------------------------------------
# 14.9 Friday gate
# ---------------------------------------------------------------------------
class TestFridayGate(unittest.TestCase):
    """Sydney Friday 05:00-05:59 window, once per Friday (D-LD1)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state.json"
        patcher = patch.object(ld, "STATE_PATH", self.state)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _at(self, y, m, d, h):
        return datetime(y, m, d, h, 30,
                        tzinfo=ZoneInfo("Australia/Sydney"))

    def test_gate_fires_once_per_sydney_friday(self):
        """Open inside the window; closed after the state is written."""
        now = self._at(2026, 9, 11, 5)   # Friday
        self.assertTrue(ld.friday_gate_open(now))
        ld.friday_gate_mark_fired(now)
        self.assertFalse(ld.friday_gate_open(now))
        self.assertTrue(self.state.exists())

    def test_gate_closed_outside_window(self):
        """Saturday 05:00 and Friday 06:00 are closed."""
        self.assertFalse(ld.friday_gate_open(self._at(2026, 9, 12, 5)))
        self.assertFalse(ld.friday_gate_open(self._at(2026, 9, 11, 6)))

    def test_gate_dst_aedt_2026_04_03_fires(self):
        """2026-04-03 05:00 Sydney = AEDT -> open."""
        self.assertTrue(ld.friday_gate_open(self._at(2026, 4, 3, 5)))

    def test_gate_dst_aest_2026_06_05_fires(self):
        """2026-06-05 05:00 Sydney = AEST -> open."""
        self.assertTrue(ld.friday_gate_open(self._at(2026, 6, 5, 5)))


# ---------------------------------------------------------------------------
# 14.10 Security greps
# ---------------------------------------------------------------------------
class TestSecurity(unittest.TestCase):
    """Source + transport security assertions (§14.10)."""

    def test_no_verify_false_in_core_or_extractors(self):
        """verify=False is absent from shipped sources (sandbox
        exempt). """""
        root = Path(ld.__file__).resolve().parent.parent
        for sub in ("core", "extractors"):
            for py in (root / sub).glob("*.py"):
                text = py.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("verify=False", text, str(py))

    def test_dunya_catalogue_routes_via_scrapedo(self):
        """Every catalogue page request goes to api.scrape.do. """""
        from extractors import shop_site_catalogue as ssc
        fake = MagicMock(return_value=MagicMock(
            status_code=200, json=lambda: [], raise_for_status=lambda:
            None))
        with patch.object(ssc.requests, "get", fake), \
             patch.object(ssc, "register_scrapedo_credit",
                          return_value=True):
            ssc.get_catalogue("dunya", force=True)
        for call in fake.call_args_list:
            self.assertEqual(call.args[0], "https://api.scrape.do")

    def test_no_secrets_in_log_paths(self):
        """The SCRAPEDO_API_KEY sentinel never appears in stdout. """""
        from extractors import shop_site_catalogue as ssc
        sentinel = "sentinel-secret-value-xyz"
        env = {"SCRAPEDO_API_KEY": sentinel}
        fake = MagicMock(return_value=MagicMock(
            status_code=200, json=lambda: [], raise_for_status=lambda:
            None))
        buf = io.StringIO()
        with patch.dict(os.environ, env, clear=False), \
             patch.object(ssc.requests, "get", fake), \
             patch.object(ssc, "register_scrapedo_credit",
                          return_value=True), \
             contextlib.redirect_stdout(buf):
            ssc.get_catalogue("dunya", force=True)
        self.assertNotIn(sentinel, buf.getvalue())


# ---------------------------------------------------------------------------
# 14.17 Domain gate
# ---------------------------------------------------------------------------
class TestDomainGate(unittest.TestCase):
    """§8.4 comparisons; Oreo rule; schnitzel stays OUT. """""

    def test_butchery_deal_vs_raw_meat_compares(self):
        """Raw meat deal vs raw meat master compares + can alert."""
        results = ld.match_and_detect([_deal()], [_master()], {})
        self.assertTrue(results[0].in_domain)
        self.assertEqual(results[0].matched_master,
                         "Woolworths Beef Diced 1kg")

    def test_butchery_nuggets_never_matched_never_alerted(self):
        """Butcher nuggets never compare against the sheet. """""
        results = ld.match_and_detect(
            [_deal(item="Chicken Nuggets", price=9.0)],
            [_master(name="Woolworths Chicken Nuggets 1kg",
                     sub="frozen snacks")], {})
        self.assertFalse(results[0].alert)
        self.assertEqual(results[0].matched_master, "")

    def test_butchery_patties_never_compared(self):
        """Patties are out of the butchery domain. """""
        results = ld.match_and_detect(
            [_deal(item="Beef Patties", price=9.0)],
            [_master(name="Woolworths Beef Patties 500g", size="500g",
                     sub="needs review")], {})
        self.assertFalse(results[0].alert)

    def test_schnitzel_out_of_butcher_domain(self):
        """Schnitzel stays OUT (user decision 05:04). """""
        results = ld.match_and_detect(
            [_deal(item="Chicken Schnitzel", price=11.0)],
            [_master(name="Woolworths Chicken Schnitzel 1kg",
                     sub="chicken schnitzel")], {})
        self.assertFalse(results[0].alert)
        self.assertEqual(results[0].matched_master, "")

    def test_fruitshop_deal_vs_produce_row_compares(self):
        """Fruit-shop produce vs produce master compares. """""
        results = ld.match_and_detect(
            [_deal(item="Apples Royal Gala", store="fruitopia",
                   category="fruits", price=3.20)],
            [_master(name="Woolworths Apples Royal Gala per kg",
                     size="1kg", wool=4.50, sub="apples",
                     coarse="Fruit & Veg")], {})
        self.assertTrue(results[0].alert)

    def test_fruitshop_biscuit_never_compared_fraud_oreo(self):
        """The fraud-Oreo rule: biscuits never compare. """""
        results = ld.match_and_detect(
            [_deal(item="Oreo", store="fruitopia", category="other",
                   price=2.5, unit="pack")],
            [_master(name="Oreo Original 133g", size="133g",
                     wool=2.50, sub="biscuits")], {})
        self.assertFalse(results[0].in_domain)
        self.assertFalse(results[0].alert)
        self.assertEqual(results[0].matched_master, "")

    def test_fruitshop_lebanese_bread_never_compared(self):
        """Bread at a fruit shop is out of domain. """""
        results = ld.match_and_detect(
            [_deal(item="Lebanese Bread", store="fruitopia",
                   category="other", price=1.5, unit="pack")],
            [_master(name="Woolworths Lebanese Bread", size="10 pack",
                     wool=2.00, sub="bread")], {})
        self.assertFalse(results[0].in_domain)

    def test_out_of_domain_in_tab_and_post2_never_post1(self):
        """Recorded in the tab + Post 2, never in Post 1. """""
        deals = [_deal(item="Oreo", store="fruitopia",
                       category="other", price=2.5, unit="pack")]
        results = ld.match_and_detect(deals, [_master()], {})
        rows = ld.build_rows({"fruitopia": deals})
        self.assertIn("OTHER", rows)
        post2 = "\n".join(ld.render_post2_blocks(results,
                                                 "2026-09-11"))
        self.assertIn("Oreo", post2)
        self.assertNotIn("Oreo", ld.render_post1(results,
                                                 "2026-09-11"))

    def test_out_of_domain_never_in_shopping_list_maths(self):
        """Out-of-domain items carry no pct/baseline/alert — they
        cannot influence extra-stop savings. """""
        results = ld.match_and_detect(
            [_deal(item="Oreo", store="fruitopia", category="other",
                   price=1.0, unit="pack")], [], {})
        self.assertIsNone(results[0].pct)
        self.assertIsNone(results[0].baseline_price)
        self.assertFalse(results[0].alert)
        self.assertEqual(ld.render_post1(results, "2026-09-11"),
                         "No local standouts this week")

    def test_cross_store_merge_never_joins_out_of_domain(self):
        """A domain row and an out-of-domain same-name item stay on
        separate rows. """""
        deals = {
            "dunya": [_deal(item="Beef Diced")],
            "fruitopia": [_deal(item="Beef Diced", store="fruitopia",
                                category="other", price=11.0)],
        }
        rows = ld.build_rows(deals)
        butchery_names = [r[0] for r in rows.get("BUTCHERY", [])]
        other_names = [r[0] for r in rows.get("OTHER", [])]
        self.assertEqual(len(butchery_names), 1)
        self.assertEqual(len(other_names), 1)


# ---------------------------------------------------------------------------
# 14.4 Freshness
# ---------------------------------------------------------------------------
class TestFreshness(unittest.TestCase):
    """valid_until freshness drops (§5). """""

    def _posts(self, valid_until):
        from extractors.fb_flyer_fetch import PostImages
        payload = {"valid_until": valid_until, "deals": [_deal()]}
        files = [Path("unused.jpg")]
        return [PostImages(post_ref=f"dunya-p{i}", files=files)
                for i in range(1, 4)]

    def test_expired_valid_until_dropped(self):
        """A post whose board expired yesterday is dropped."""
        posts = self._posts("2020-01-01")
        with patch("extractors.fb_flyer_fetch.fetch_store_posts",
                   return_value=posts), \
             patch("core.flyer_vision.parse_board_images",
                   return_value={"valid_until": "2020-01-01",
                                 "deals": [_deal()]}):
            with pytest.raises(FetchUnavailable):
                ld._process_store(
                    {"key": "dunya", "name": "Dunya Butchery"},
                    Path(tempfile.mkdtemp()),
                    datetime(2026, 9, 11).date())

    def test_all_null_dates_keep_three_posts(self):
        """All-null dates keep every post's deals. """""
        posts = self._posts(None)
        with patch("extractors.fb_flyer_fetch.fetch_store_posts",
                   return_value=posts), \
             patch("core.flyer_vision.parse_board_images",
                   return_value={"valid_until": None,
                                 "deals": [_deal()]}):
            deals = ld._process_store(
                {"key": "dunya", "name": "Dunya Butchery"},
                Path(tempfile.mkdtemp()),
                datetime(2026, 9, 11).date())
        self.assertEqual(len(deals), 3)

    def test_over_three_posts_keeps_three_most_recent(self):
        """The fetch layer caps stores at 3 posts (most recent)."""
        from extractors import fb_flyer_fetch as ff
        html_parts = []
        for i in range(5):
            html_parts.append(
                f'<script>top_level_post_id":"{9000000 + i}"</script>')
            html_parts.append(
                f'<img src="https://scontent.example.net/x/'
                f'{2000000 + i}_101_102_999.jpg?cstp=mx960x960">')
        html = "\n".join(html_parts)

        def fake_download(url, dest):
            dest.write_bytes(b"x" * 40_000)
            return dest

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ff.requests, "get",
                          return_value=type("R", (), {
                              "status_code": 200, "text": html,
                              "content": b""})()), \
             patch.object(ff, "_download", fake_download):
            posts = ff.fetch_store_posts(ff.STORES[0], Path(tmp))
        self.assertEqual(len(posts), 3)


if __name__ == "__main__":
    unittest.main()
