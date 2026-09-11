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
            "size": size, "wool_price": wool, "coles_amt": coles,
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
        """Header row frozen (layout 2026-09-12: header + item rows
        ONLY — no validity row); header = Product + the 4 store
        names; row 2 is the first ITEM row."""
        ws = FakeWorksheet()
        self._rebuild(ws, {"dunya": [_deal()]})
        self.assertEqual(ws.frozen, 1)
        header = ws.updates[-1][0][0]
        self.assertEqual(header[0], "Product")
        self.assertEqual(header[1:], [n for _k, n in ld.TAB_COLUMNS])
        self.assertNotEqual(ws.updates[-1][0][1][0],
                            "Prices valid until")

    def test_section_order_fruits_butchery_other(self):
        """Items appear in FRUITS, BUTCHERY, OTHER order — written as
        plain item rows, NO section-title rows (layout 2026-09-12)."""
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
        names = [str(row[0]).strip() for row in grid[1:]]
        for label in ("FRUITS", "BUTCHERY", "OTHER"):
            self.assertNotIn(label, names)   # no structural rows
        self.assertTrue(names[0].startswith("Apples"))
        self.assertTrue(names[1].startswith("Beef Diced"))
        self.assertTrue(names[2].startswith("Oreo"))

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
        # 10-col layout v2: abusalim special = idx 8 (bulk price),
        # fruitopia special = idx 6 on the SAME canonical row.
        self.assertEqual(row[8], 2.99)
        self.assertEqual(row[6], 3.00)

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
        """Assert-by-grep: the master sheet name occurs exactly
        twice in core/local_deals.py — the read helper's docstring
        and the Round-3 §4.2 mirror wiring in ingest_code (the ONLY
        place code may open the master tab by name)."""
        source = Path(ld.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("Products_Master"), 2)


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

    def test_plural_forms_match(self):
        """User rule 2026-09-07: 'Strawberries' matches the
        'Strawberry' master row (plural-folded containment)."""
        results = self._detect(
            [_deal(item="Strawberries", store="fruitopia",
                   category="fruits", price=2.99, unit="kg")],
            [_master(name="Woolworths Strawberry 500g",
                     size="500g", wool=5.00, sub="strawberries",
                     coarse="Fruit & Veg")])
        self.assertEqual(results[0].matched_master,
                         "Woolworths Strawberry 500g")
        self.assertTrue(results[0].alert)

    def test_bag_compares_per_kg_vs_largest_master_bag(self):
        """User rule 2026-09-07: a 5kg bag deal compares PER KILO
        against the LARGEST matching master bag (2kg over 1kg)."""
        results = self._detect(
            [_deal(item="Onions 5kg Bag", store="fruitopia",
                   category="fruits", price=7.50, unit="ea")],
            [_master(name="Woolworths Onions 1kg Bag", size="1kg",
                     wool=3.00, sub="onions", coarse="Fruit & Veg",
                     idx=2),
             _master(name="Woolworths Onions 2kg Bag", size="2kg",
                     wool=5.00, sub="onions", coarse="Fruit & Veg",
                     idx=3)])
        self.assertEqual(results[0].matched_master,
                         "Woolworths Onions 2kg Bag")     # largest
        self.assertEqual(results[0]._basis, "kg")
        # deal $1.50/kg vs master $2.50/kg -> 40% under -> alert
        self.assertTrue(results[0].alert)

    def test_bag_equal_rate_no_alert(self):
        """5kg $12.50 ($2.50/kg) vs 2kg $5.00 ($2.50/kg) -> pct 0."""
        results = self._detect(
            [_deal(item="Onions 5kg Bag", store="fruitopia",
                   category="fruits", price=12.50, unit="ea")],
            [_master(name="Woolworths Onions 2kg Bag", size="2kg",
                     wool=5.00, sub="onions", coarse="Fruit & Veg")])
        self.assertFalse(results[0].alert)
        self.assertEqual(results[0].pct, pytest.approx(0.0))

    def test_bag_never_vs_loose_each(self):
        """No weight-size master -> 'no comparable bag size'; a bag
        is never compared against a loose each-price."""
        results = self._detect(
            [_deal(item="Onions 5kg Bag", store="fruitopia",
                   category="fruits", price=7.50, unit="ea")],
            [_master(name="Woolworths Brown Onions", size="",
                     wool=2.50, sub="onions", coarse="Fruit & Veg")])
        self.assertIsNone(results[0].pct)
        self.assertFalse(results[0].alert)
        self.assertIn("no comparable bag size", results[0].note)

    def test_expired_prices_not_compared(self):
        """User rule 2026-09-07: a post whose validity ended before
        today (Sydney) is recorded but never compared or alerted."""
        from datetime import timedelta
        yesterday = ld.sydney_today() - timedelta(days=1)
        results = self._detect(
            [_deal(item="Strawberries", store="fruitopia",
                   category="fruits", price=0.50, unit="kg",
                   valid_until=yesterday)],
            [_master(name="Woolworths Strawberry 500g",
                     size="500g", wool=5.00, sub="strawberries",
                     coarse="Fruit & Veg")])
        self.assertIsNone(results[0].pct)
        self.assertFalse(results[0].alert)
        self.assertIn("prices expired", results[0].note)

    def test_valid_prices_still_compared(self):
        """A post still inside its validity period compares normally."""
        from datetime import timedelta
        tomorrow = ld.sydney_today() + timedelta(days=2)
        results = self._detect(
            [_deal(item="Strawberries", store="fruitopia",
                   category="fruits", price=2.99, unit="kg",
                   valid_until=tomorrow)],
            [_master(name="Woolworths Strawberry 500g",
                     size="500g", wool=5.00, sub="strawberries",
                     coarse="Fruit & Veg")])
        self.assertTrue(results[0].alert)


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
        # Layout v2: numeric specials price in the shop's SPECIAL
        # column (abusalim = idx 8), the bulk note shop-tagged in
        # Comments (idx 9).
        self.assertEqual(rows["FRUITS"][0][8], 2.99)
        self.assertEqual(rows["FRUITS"][0][9],
                         "[ABS] multi buy 5kg for $2.99")
        results = ld.match_and_detect([deal], [], {})
        self.assertEqual(results[0].multibuy_note,
                         "multi buy 5kg for $2.99 — $0.60/kg")
        mb = _deal(item="Sausages", kind="multibuy", price=15.0,
                   unit="pack", multibuy_qty=2)
        rows2 = ld.build_rows({"dunya_fb": [mb]})
        # Layout v2: dunya special (FB) = idx 2, Comments = idx 9.
        self.assertEqual(rows2["BUTCHERY"][0][2], 7.5)
        self.assertEqual(rows2["BUTCHERY"][0][9],
                         "[DUN] multi buy 2 for $15.00 — $7.50/ea")

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


# ---------------------------------------------------------------------------
# Layout v2: validity stamps, sweep, special-first reads, manual entry
# ---------------------------------------------------------------------------
def _v2_grid():
    """Header + validity row of the 10-column layout v2."""
    return [["Product"] + [n for _k, n in ld.TAB_COLUMNS],
            ["Prices valid until", "n/a (live site)",
             "", "", "", "", "", "", "", ""]]


def _v2_ws(data_rows):
    """FakeWorksheet preloaded with a layout-v2 tab."""
    ws = FakeWorksheet()
    ws.rows = _v2_grid() + [list(r) for r in data_rows]
    return ws


class TestValidityStamps(unittest.TestCase):
    """' (till 12 Sep)' stamp parse/expire helpers."""

    def test_stamp_and_strip_roundtrip(self):
        stamped = ld._stamp_validity(0.75, datetime(2026, 9, 12).date())
        self.assertEqual(stamped, "0.75 (till 12 Sep)")
        self.assertEqual(ld._strip_till(stamped), "0.75")
        self.assertEqual(ld._stamp_validity(0.75, None), 0.75)

    def test_cell_till_date_parses_day_month(self):
        d = datetime(2026, 9, 7).date()
        self.assertEqual(ld._cell_till_date("0.75 (till 12 Sep)", d),
                         datetime(2026, 9, 12).date())
        self.assertEqual(
            ld._cell_till_date("0.75 (till 12 September)", d),
            datetime(2026, 9, 12).date())
        self.assertIsNone(ld._cell_till_date("0.75", d))
        self.assertIsNone(ld._cell_till_date("[multi buy 2 for $1.50]",
                                             d))

    def test_special_expired_boundary(self):
        d = datetime(2026, 9, 7).date()
        self.assertTrue(ld._special_expired("0.75 (till 6 Sep)", d))
        self.assertFalse(ld._special_expired("0.75 (till 7 Sep)", d))
        self.assertFalse(ld._special_expired("0.75 (till 12 Sep)", d))
        self.assertFalse(ld._special_expired("0.75", d))  # undated

    def test_numeric_price_ignores_stamp(self):
        self.assertEqual(ld._numeric_price("0.75 (till 12 Sep)"),
                         pytest.approx(0.75))


class TestTabStorePrice(unittest.TestCase):
    """Special-first reading with permanent fallback."""

    TODAY = datetime(2026, 9, 7).date()

    def test_special_wins_over_permanent(self):
        row = ["Carrots /kg", "", "", "", "", 6.50, 0.75, "", "", ""]
        price, source = ld.tab_store_price(row, "fruitopia",
                                           today=self.TODAY)
        self.assertEqual(price, pytest.approx(0.75))
        self.assertEqual(source, "special")

    def test_expired_special_skipped_permanent_fallback(self):
        row = ["Carrots /kg", "", "", "", "", 6.50,
               "0.75 (till 6 Sep)", "", "", ""]
        price, source = ld.tab_store_price(row, "fruitopia",
                                           today=self.TODAY)
        self.assertEqual(price, pytest.approx(6.50))
        self.assertEqual(source, "permanent")

    def test_non_numeric_offer_text_is_none(self):
        row = ["Carrots /ea", "", "", "", "", "",
               "[multi buy 2 for $1.50 — $0.75/ea]", "", "", ""]
        price, source = ld.tab_store_price(row, "fruitopia",
                                           today=self.TODAY)
        self.assertIsNone(price)
        self.assertEqual(source, "")

    def test_other_shops_cells_invisible(self):
        row = ["Carrots /kg", "", "", "", "", 6.50, 0.75, "", "", ""]
        price, _src = ld.tab_store_price(row, "merjan",
                                         today=self.TODAY)
        self.assertIsNone(price)


class TestSweepExpiredSpecials(unittest.TestCase):
    """Morning sweep: dated expired cells cleared, everything else
    kept (rows never deleted, permanent never touched)."""

    TODAY = datetime(2026, 9, 7).date()

    def test_expired_cell_cleared_comment_dies_with_it(self):
        # FIX-4 (user rule 2026-09-09): the shop-tagged comment
        # segment is removed WITH its expired price; other shops'
        # segments survive.
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 6 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea; "
             "[MER] 3 for $4.00 — $1.33/ea"],
        ])
        lines = ld.sweep_expired_specials(ws, today=self.TODAY)
        self.assertEqual(len(lines), 1)
        self.assertIn("Carrots", lines[0])
        grid = ws.get_all_values()
        self.assertEqual(grid[3][0], "Carrots /ea")   # row KEPT
        self.assertEqual(grid[3][6], "")              # cell cleared
        self.assertNotIn("[FRU]", grid[3][9])         # FRU segment died
        self.assertIn("[MER]", grid[3][9])            # MER untouched

    def test_future_dated_and_undated_specials_kept(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "", ""],
            ["Apples /kg", "", "", "", "", "", 2.50, "", "", ""],
        ])
        self.assertEqual(ld.sweep_expired_specials(
            ws, today=self.TODAY), [])
        grid = ws.get_all_values()
        self.assertEqual(grid[3][6], "0.75 (till 12 Sep)")
        self.assertEqual(grid[4][6], 2.50)

    def test_permanent_cell_never_swept_even_if_stamped(self):
        ws = _v2_ws([
            # stamp sits in the FRUITOPIA PERM column (idx 5) —
            # permanent columns are outside the sweep's remit
            ["FRUITS", "", "", "", "", "6.50 (till 1 Sep)",
             "", "", "", ""],
        ])
        self.assertEqual(ld.sweep_expired_specials(
            ws, today=self.TODAY), [])
        self.assertEqual(ws.get_all_values()[2][5],
                         "6.50 (till 1 Sep)")

    def test_expired_row2_summary_stamp_cleared(self):
        """Layout 2026-09-12: the sweep NEVER touches the legacy
        'Prices valid until' row (no re-derivation, no clearing) —
        it only sweeps expired special CELLS on item rows."""
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 6 Sep)", "", "", ""],
        ])
        ws.rows[1][6] = "valid until Sun 06 Sep"   # fruitopia sp
        ws.rows[1][4] = "valid until Sat 12 Sep"   # merjan sp
        lines = ld.sweep_expired_specials(ws, today=self.TODAY)
        grid = ws.get_all_values()
        self.assertEqual(grid[3][6], "")           # expired cell gone
        self.assertEqual(grid[1][6], "valid until Sun 06 Sep")
        self.assertEqual(grid[1][4], "valid until Sat 12 Sep")
        self.assertFalse(any("re-derived" in ln or "stamp" in ln
                             for ln in lines))

    def test_expired_stamp_survives_while_undated_special_live(self):
        # R2-6 (D21): an UNDATED special is a live special — its
        # store's stamp is never deleted while it remains (there is no
        # till date to re-derive from, so the stamp is left as-is).
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "", 0.75, "", "", ""],
        ])
        ws.rows[1][6] = "valid until Sun 06 Sep"   # expired stamp
        lines = ld.sweep_expired_specials(ws, today=self.TODAY)
        self.assertEqual(lines, [])
        self.assertEqual(ws.get_all_values()[1][6],
                         "valid until Sun 06 Sep")

    def test_no_write_when_nothing_expired(self):
        ws = _v2_ws([])
        ws.clear_calls = 0
        self.assertEqual(ld.sweep_expired_specials(ws,
                                                   today=self.TODAY),
                         [])
        self.assertEqual(ws.clear_calls, 0)

    def test_legacy_summary_stamp_text_cleared_from_item_row(self):
        """The 2026-09-12 08:32 incident: a raw out-of-CLI write
        landed the RETIRED row-2 summary text ('valid until Sun 13
        Sep') in the Fruitopia cell of the FIRST ITEM row — the old
        stamp ROW is gone, so sheet row 2 is now an item row. Such
        text is never a price, the numeric readers ignore it, and the
        '(till …)' expiry matcher can never clear it: the sweep
        removes it on sight. Legal cells are never touched."""
        ws = _v2_ws([
            ["Halal chicken breast diced /kg", "13.99", "", "", "",
             "", "valid until Sun 13 Sep", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.99 (till 20 Sep)", "", "", ""],
        ])
        lines = ld.sweep_expired_specials(ws, today=self.TODAY)
        grid = ws.get_all_values()
        self.assertEqual(len(lines), 1)
        self.assertIn("legacy summary stamp text", lines[0])
        self.assertEqual(grid[2][6], "")           # defect cleared
        self.assertEqual(grid[2][1], "13.99")      # perm untouched
        self.assertEqual(grid[3][6], "0.99 (till 20 Sep)")


class TestSweepStampReDerivationR2_6(unittest.TestCase):
    """The R2-6 (D21) row-2 stamp RE-DERIVATION is RETIRED (layout
    2026-09-12: no summary row). What survives is the D21 acceptance
    invariant in its new form: sweeping an UNRELATED expired cell
    never disturbs other live cells of the same store."""

    TODAY = datetime(2026, 9, 8).date()

    def _merjan_ws(self, stamp, rows):
        ws = _v2_ws([["BUTCHERY", "", "", "", "", "", "", "", "", ""]]
                    + rows)
        ws.rows[1][4] = stamp        # merjan special column
        return ws

    def test_stamp_kept_when_matching_live_special_remains(self):
        # The D21 acceptance: sweeping an UNRELATED expired Merjan
        # cell keeps 'valid until Fri 11 Sep' (row 104 still live).
        # grid: [0] header, [1] stamps, [2] BUTCHERY, [3..] items.
        ws = self._merjan_ws("valid until Fri 11 Sep", [
            ["Lamb Curry /ea", "", "", "", "27.99 (till 11 Sep)", "",
             "", "", "", ""],       # the real row-104 shape (live)
            ["Beef Mince /kg", "", "", "", "8.99 (till 11 Sep)", "",
             "", "", "", ""],       # live
            ["Chicken /ea", "", "", "", "12.50 (till 5 Sep)", "",
             "", "", "", ""],       # expired — swept
        ])
        lines = ld.sweep_expired_specials(ws, today=self.TODAY)
        grid = ws.get_all_values()
        self.assertEqual(grid[5][4], "")            # expired cell gone
        self.assertEqual(grid[4][4], "8.99 (till 11 Sep)")
        self.assertEqual(grid[3][4], "27.99 (till 11 Sep)")
        # Legacy stamp row is never modified by the sweep.
        self.assertEqual(grid[1][4], "valid until Fri 11 Sep")
        self.assertTrue(all("stamp" not in ln for ln in lines))


class TestSetStorePrices(unittest.TestCase):
    """Manual pricing entry: canonical match, stamps, tagged notes."""

    TILL = datetime(2026, 9, 12).date()

    def test_note_with_dollar_amounts_lands_verbatim_r2_10(self):
        """R2-10 (R14): a --note carrying $<digit> must land VERBATIM
        in the Comments cell — '$15', '$2x', '\\$1' all survive. (The
        verification round's 'eaten $1' receipt shows the note already
        mangled ON THE COMMAND LINE — the verifier's shell expanded
        the unquoted $15; the code path writes the note verbatim, and
        this test pins that contract so a future re.sub-with-user-repl
        regression cannot slip in.)"""
        ws = _v2_ws([["BUTCHERY", "", "", "", "", "", "", "", "", ""]])
        lines = ld.set_store_prices(
            ws, "merjan", "special",
            [{"item": "beef mince", "price": 8.99, "unit": "kg",
              "note": "multi buy 2 for $15"}],
            till=self.TILL)
        self.assertTrue(lines)
        grid = ws.get_all_values()
        # Q17 (Round 3): the butchery entry is 'Halal '-prefixed at
        # normalization — the note contract is unchanged by it.
        comment = next(r[9] for r in grid if str(r[0]).lower()
                       .startswith("halal beef mince"))
        self.assertEqual(comment, "[MER] multi buy 2 for $15")

        # Second write on the same row replaces the segment — still
        # verbatim, '$2x' intact.
        ld.set_store_prices(
            ws, "merjan", "special",
            [{"item": "beef mince", "price": 7.99, "unit": "kg",
              "note": "deal $2x this week only"}],
            till=self.TILL)
        grid = ws.get_all_values()
        comment = next(r[9] for r in grid if str(r[0]).lower()
                       .startswith("halal beef mince"))
        self.assertEqual(comment, "[MER] deal $2x this week only")

    def test_new_row_appended_in_shop_section_with_stamp(self):
        """Round 3 (Q27): a new row APPENDS AT GRID END — never a
        mid-tab insert inside the section block. Layout 2026-09-12:
        no row-2 summary stamp is written."""
        ws = FakeWorksheet()
        ws.rows = [["Product"] + [n for _k, n in ld.TAB_COLUMNS]]
        lines = ld.set_store_prices(ws, "fruitopia", "special",
                                    [{"item": "Carrots",
                                      "price": 0.75, "unit": "ea"}],
                                    till=self.TILL)
        grid = ws.get_all_values()
        self.assertEqual(grid[-1][0], "Carrots /ea")   # grid end
        self.assertEqual(grid[-1][6], "0.75 (till 12 Sep)")
        stamp_rows = [r for r in grid
                      if str(r[0]).strip() == "Prices valid until"]
        self.assertEqual(stamp_rows, [])
        self.assertIn("[new row]", lines[0])

    def test_existing_row_matched_ignoring_unit_suffix(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /kg", "", "", "", "", "", 1.20, "", "", ""],
        ])
        lines = ld.set_store_prices(ws, "fruitopia", "special",
                                    [{"item": "carrots",
                                      "price": 0.75, "unit": "ea"}])
        grid = ws.get_all_values()
        self.assertEqual(len(grid), 4)            # no row appended
        self.assertEqual(grid[3][6], 0.75)
        self.assertIn("[row 4]", lines[0])

    def test_permanent_write_has_no_stamp(self):
        ws = _v2_ws([])
        ld.set_store_prices(ws, "fruitopia", "perm",
                            [{"item": "Carrots", "price": 6.50,
                              "unit": "kg"}])
        grid = ws.get_all_values()
        self.assertEqual(grid[-1][5], 6.50)       # fruitopia PERM
        self.assertEqual(grid[1][5], "")          # no validity stamp
        self.assertEqual(grid[-1][6], "")         # special untouched

    def test_notes_shop_tagged_and_merged_across_shops(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "", 0.75, "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        # abusalim is a FRUITS shop -> same section block -> merge
        ld.set_store_prices(ws, "abusalim", "special",
                            [{"item": "Carrots", "price": 0.80,
                              "unit": "ea",
                              "note": "bulk 3 for $2"}])
        grid = ws.get_all_values()
        self.assertEqual(
            grid[3][9],
            "[FRU] multi buy 2 for $1.50 — $0.75/ea; "
            "[ABS] bulk 3 for $2")

    def test_butchery_entry_reuses_plain_row_id2(self):
        """ID-2 (user directive 2026-09-11): the halal prefix is
        source-based and IGNORED for row reuse — a butchery entry
        reuses the existing plain-named row (prices + comments only,
        Item_Code untouched, NO near-duplicate row). Supersedes the
        Round-3 Q11 separate-row expectation for the LD tab: the read
        side joins LD rows by Item_Code pairing (§8), not by the
        Col A prefix. Divergence flagged in implementation-plan.md
        (auto-ingest batch, AI-M2 verbatim quote)."""
        ws = _v2_ws([
            ["BUTCHERY", "", "", "", "", "", "", "", "", ""],
            ["Beef Diced /kg", "", "", 9.50, "", "", "", "", "",
             ""],
        ])
        lines = ld.set_store_prices(ws, "merjan", "special",
                                    [{"item": "beef diced",
                                      "price": 8.99, "unit": "kg"}])
        grid = ws.get_all_values()
        self.assertEqual(grid[3][3], 9.50)   # dunya perm untouched
        self.assertEqual(grid[3][4], 8.99)   # merjan special REUSES
        self.assertEqual(grid[3][0], "Beef Diced /kg")  # name kept
        self.assertEqual(len(grid), 4)       # NO near-duplicate row

    def test_unreadable_entry_reported_not_written(self):
        ws = _v2_ws([])
        lines = ld.set_store_prices(ws, "fruitopia", "special",
                                    [{"item": "", "price": 0.75,
                                      "unit": "ea"}])
        self.assertIn("skipped", lines[0])
        self.assertEqual(len(ws.get_all_values()), 2)


class TestRebuildPreservation(unittest.TestCase):
    """Layout-v2 rebuild: perm + non-run shops + comments survive."""

    def _rebuild(self, ws, deals, keys, validity=None):
        rows = ld.build_rows(deals)
        ld.rebuild_tab(ws, rows, keys)     # validity param retired

    def test_permanent_survives_special_rebuild(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /kg", 6.49, "", "", "", "", "0.75 (till 6 Sep)",
             "", "", ""],
        ])
        deals = {"fruitopia": [_deal(item="Carrots",
                                     store="fruitopia",
                                     category="fruits", price=0.80,
                                     unit="kg",
                                     valid_until=datetime(
                                         2026, 9, 12).date())]}
        self._rebuild(ws, deals, ["fruitopia"])
        grid = ws.get_all_values()
        carrot = next(r for r in grid if r[0] == "Carrots /kg")
        self.assertEqual(carrot[1], 6.49)         # dunya PERM kept
        self.assertEqual(carrot[6], "0.8 (till 12 Sep)")
        stamp_rows = [r for r in grid
                      if str(r[0]).strip() == "Prices valid until"]
        self.assertEqual(stamp_rows, [])          # no summary row

    def test_non_run_shop_special_survives(self):
        ws = _v2_ws([
            ["BUTCHERY", "", "", "", "", "", "", "", "", ""],
            ["Beef Diced /kg", "", 12.99, "", 9.50, "", "", "", "",
             ""],
        ])
        deals = {"dunya_fb": [_deal(item="Beef Diced", store="dunya",
                                    category="butchery",
                                    price=11.99)]}
        self._rebuild(ws, deals, ["dunya_fb"])
        grid = ws.get_all_values()
        beef = next(r for r in grid if r[0] == "Beef Diced /kg")
        self.assertEqual(beef[2], 11.99)          # this run rebuilt
        self.assertEqual(beef[4], 9.50)           # MERJAN special kept

    def test_comment_segments_merge_both_directions(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "", 0.75, "", "",
             "[MER] bulk 3 for $2"],
        ])
        deals = {"fruitopia": [_deal(
            item="Carrots", store="fruitopia", category="fruits",
            price=0.75, unit="ea", kind="multibuy", multibuy_qty=2)]}
        self._rebuild(ws, deals, ["fruitopia"])
        grid = ws.get_all_values()
        carrot = next(r for r in grid if r[0] == "Carrots /ea")
        self.assertIn("[MER] bulk 3 for $2", carrot[9])
        self.assertIn("[FRU]", carrot[9])
        self.assertIn("multi buy 2 for", carrot[9])

    def test_row_only_other_shop_data_reappended(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Mangoes /ea", "", "", "", 3.00, "", "", "", "", ""],
        ])
        deals = {"fruitopia": [_deal(item="Apples",
                                     store="fruitopia",
                                     category="fruits", price=2.00)]}
        self._rebuild(ws, deals, ["fruitopia"])
        grid = ws.get_all_values()
        mango = next(r for r in grid if r[0] == "Mangoes /ea")
        self.assertEqual(mango[4], 3.00)   # merjan-only row survives

    def test_stale_special_of_run_shop_cleared(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Mangoes /ea", "", "", "", "", "", 3.00, "", "", ""],
        ])
        deals = {"fruitopia": [_deal(item="Apples",
                                     store="fruitopia",
                                     category="fruits", price=2.00)]}
        self._rebuild(ws, deals, ["fruitopia"])
        grid = ws.get_all_values()
        self.assertFalse(any(r[0] == "Mangoes /ea" and r[6]
                             for r in grid))


class TestValidUntilAttach(unittest.TestCase):
    """Deals carry their post's validity into the tab builders."""

    def test_timeline_deals_carry_post_validity(self):
        post = type("P", (), {
            "text": "Valid until 12 September\nSPECIALS\n"
                    "Carrots 0.75/ea",
            "image_urls": [], "post_ref": "fru-p1",
            "creation_time": None})()
        with patch("extractors.fb_timeline_fetch."
                   "fetch_timeline_posts", return_value=[post]), \
             patch.object(ld, "extract_post_deals",
                          return_value=([{"item": "Carrots",
                                          "price": 0.75,
                                          "unit": "ea"}],
                                        "text", None)):
            deals = ld._process_store_timeline(
                {"key": "fruitopia", "name": "Fruitopia Mt Druitt",
                 "pipeline": "timeline"},
                Path("unused"), datetime(2026, 9, 7).date())
        self.assertEqual(deals[0]["valid_until"],
                         datetime(2026, 9, 12).date())

    def test_photos_deals_carry_board_validity(self):
        from extractors.fb_flyer_fetch import PostImages
        posts = [PostImages(post_ref="dunya-p1",
                            files=[Path("x.jpg")])]
        with patch("extractors.fb_flyer_fetch.fetch_store_posts",
                   return_value=posts), \
             patch("core.flyer_vision.parse_board_images",
                   return_value={"valid_until": "2026-09-12",
                                 "deals": [{"item": "Beef Diced",
                                            "price": 9.0}]}):
            deals = ld._process_store(
                {"key": "dunya", "name": "Dunya Butchery"},
                Path("unused"), datetime(2026, 9, 7).date())
        self.assertEqual(deals[0]["valid_until"],
                         datetime(2026, 9, 12).date())

    def test_build_rows_stamps_special_cell_with_deal_date(self):
        deals = {"fruitopia": [_deal(item="Carrots",
                                     store="fruitopia",
                                     category="fruits", price=0.75,
                                     unit="ea",
                                     valid_until=datetime(
                                         2026, 9, 12).date())]}
        rows = ld.build_rows(deals)
        self.assertEqual(rows["FRUITS"][0][6], "0.75 (till 12 Sep)")
        self.assertEqual(rows["FRUITS"][0][9], "")  # no note, no tag


class TestFridayGateRetired(unittest.TestCase):
    """B6 retirement (plan S3.5): --friday-gate only prints the
    notice and exits 0 — no FB fetch, no sheet write, no telegram."""

    def test_friday_gate_retired_notice(self):
        import argparse
        import contextlib
        import io
        import sys
        from pathlib import Path
        from unittest.mock import patch

        _root = Path(__file__).resolve().parent.parent.parent
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        import grocery_price_cli as gpc

        args = argparse.Namespace(
            friday_gate=True, daily_scan=False, ingest=None,
            ignore=None, dunya_site=False, dry_run=True,
            no_telegram=True, stores=None, refresh_catalogue=False,
            provision_topic=False, set_permanent=None,
            set_special=None, till=None, note=None,
            expire_sweep=False, set_date=None, post_log=None)
        with patch.object(gpc, "_load_env"), \
                patch("core.local_deals.run_local_deals") as run_ld, \
                patch("core.local_deals.run_daily_scan") as run_ds:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = gpc._cmd_local_deals(args)
        self.assertEqual(rc, 0)
        self.assertIn("RETIRED", buf.getvalue())
        run_ld.assert_not_called()
        run_ds.assert_not_called()

    def test_daily_scan_still_runs(self):
        """--daily-scan is untouched by the Friday retirement."""
        import argparse
        import contextlib
        import io
        import sys
        from pathlib import Path
        from unittest.mock import patch

        _root = Path(__file__).resolve().parent.parent.parent
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        import grocery_price_cli as gpc

        args = argparse.Namespace(
            friday_gate=False, daily_scan=True, ingest=None,
            ignore=None, dunya_site=False, dry_run=True,
            no_telegram=True, stores=None, refresh_catalogue=False,
            provision_topic=False, set_permanent=None,
            set_special=None, till=None, note=None,
            expire_sweep=False, set_date=None, post_log=None,
            force=False)
        with patch.object(gpc, "_load_env"), \
                patch("core.local_deals.run_daily_scan",
                      return_value=0) as run_ds:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = gpc._cmd_local_deals(args)
        self.assertEqual(rc, 0)
        run_ds.assert_called_once()


class TestValidityStampsFromRealPost(unittest.TestCase):
    """Checker round 2026-09-08: the REAL Fruitopia anniversary text
    ("Saturday & Sunday, 5 & 6 September") must produce (till 6 Sep)
    stamps — never 12/19 Sep (the pre-rework bad data)."""

    TEXT = (
        "\U0001f389 FRUITOPIA MT DRUITT IS TURNING 3!\n"
        "\ud83d\udd00 Saturday & Sunday, 5 & 6 September\n"
        "\ud83e\udd6c Cos Lettuce \u2013 99\u00a2 each\n"
        "\ud83c\udf73 Sweet Corn \u2013 88\u00a2 each\n"
        "\ud83e\uddc5 Celery \u2013 2 for $2.99\n"
        "\ud83e\udd69 Strawberries \u2013 $1.80 each\n"
        "\u23f3 Saturday & Sunday only \u2014 while stocks last!"
    )

    def test_parser_gets_6_sep_not_12_or_19(self):
        from datetime import date
        from extractors.deal_text import parse_validity_end
        got = parse_validity_end(self.TEXT,
                                 today=date(2026, 9, 7))
        self.assertEqual(got, date(2026, 9, 6))

    def test_ingest_stamps_cells_till_6_sep(self):
        from datetime import date
        from extractors.deal_text import (parse_fruitopia_deals,
                                          parse_validity_end)
        deals = parse_fruitopia_deals(self.TEXT)
        valid = parse_validity_end(self.TEXT, today=date(2026, 9, 7))
        stamped = [ld._stamp_validity(d.get("price", ""),
                                      valid) for d in deals[:2]]
        self.assertTrue(all("(till 6 Sep)" in c for c in stamped))


class TestRestampUndated(unittest.TestCase):
    """--set-date must re-stamp the SHEET (checker fix 2026-09-08):
    undated special cells get the date; dated cells keep their own.
    Layout 2026-09-12: no row-2 summary stamp."""

    def _grid(self):
        return [
            ["Product"] + [""] * 9,
            ["Prices valid until", "n/a (live site)"] + [""] * 8,
            ["FRUITS"] + [""] * 9,
            ["Cos Lettuce /ea", "", "", "", "", "", "0.99",
             "", "", ""],
            ["Celery /ea", "", "", "", "", "", "2 for $2.99",
             "", "", ""],
            ["Carrots /kg", "", "", "", "", "",
             "0.75 (till 5 Sep)", "", "", ""],
        ]

    def test_undated_cells_stamped_row2_updated(self):
        from datetime import date
        grid, n = ld._restamp_undated(self._grid(), "fruitopia",
                                      date(2026, 9, 11))
        self.assertEqual(n, 2)                    # 2 undated cells
        self.assertIn("(till 11 Sep)", grid[3][6])
        self.assertIn("(till 11 Sep)", grid[4][6])
        # legacy stamp row untouched (retired layout)
        self.assertEqual(grid[1][6], "")
        self.assertIn("(till 5 Sep)", grid[5][6])  # dated kept

    def test_new_layout_items_all_stamped(self):
        """On the 2026-09-12 layout (no stamp/section rows) every
        undated special cell of the store is stamped — the old
        row-2 guard never blocked stamping."""
        from datetime import date
        grid_in = [
            ["Product"] + [""] * 9,
            ["Cos Lettuce /ea", "", "", "", "", "", "0.99",
             "", "", ""],
            ["Celery /ea", "", "", "", "", "", "2 for $2.99",
             "", "", ""],
        ]
        grid, n = ld._restamp_undated(grid_in, "fruitopia",
                                      date(2026, 9, 11))
        self.assertEqual(n, 2)
        self.assertIn("(till 11 Sep)", grid[1][6])
        self.assertIn("(till 11 Sep)", grid[2][6])

    def test_unknown_store_noop(self):
        from datetime import date
        grid, n = ld._restamp_undated(self._grid(), "nope",
                                      date(2026, 9, 11))
        self.assertEqual(n, 0)


class TestMultibuySingleDivider(unittest.TestCase):
    """FIX-3 (defect D1): one convention, one divider.

    The text parser returns the BUNDLE TOTAL (vision-schema contract);
    _cell_for is the ONLY effective_unit_rate call on the write path.
    Live symptom was a double division: '2 for $2.99' written as 0.75
    with the note '[multi buy 2 for $1.50 — $0.75/ea]'."""

    FRUT_TEXT = (
        "\U0001f34e Celery \u2013 2 for $2.99\n"
        "\U0001f34e Carrots 1kg Bag \u2013 2 for $2.99\n"
    )

    def test_real_frut_text_cell_and_note_correct(self):
        from extractors.deal_text import parse_fruitopia_deals
        deals = parse_fruitopia_deals(self.FRUT_TEXT)
        converted = [ld._to_vision_deal(d, "fruits") for d in deals]
        for deal in converted:
            cell, note = ld._cell_for(deal)
            self.assertEqual(cell, 1.5)          # 2.99/2 — ONCE
            self.assertEqual(note,
                             "multi buy 2 for $2.99 — $1.50/ea")

    def test_vision_any2_6_dollar_deal(self):
        # Vision-schema "Any 2 | $6.00" (price = bundle total).
        cell, note = ld._cell_for({
            "item": "Soft Drink Cans", "price": 6.00, "unit": "ea",
            "price_kind": "multibuy", "multibuy_qty": 2,
        })
        self.assertEqual(cell, 3.0)
        self.assertEqual(note, "multi buy 2 for $6.00 — $3.00/ea")

    def test_vision_bulk_pack_cell(self):
        # "10kg box $55" — bulk packs carry the bundle price as-is.
        cell, note = ld._cell_for({
            "item": "Potatoes", "price": 55.0, "unit": "ea",
            "price_kind": "bulk_pack", "bulk_size": "10kg",
        })
        self.assertEqual(cell, 55.0)
        self.assertEqual(note, "multi buy 10kg for $55.00")

    def test_scan_path_gets_true_bundle_total(self):
        # The standout scan (match_and_detect) reads price as the
        # bundle total too — the per-unit note must divide 2.99 -> 1.50
        # exactly once from the parser's bundle.
        results = ld.match_and_detect([{
            "store_key": "fruitopia", "store_name": "Fruitopia",
            "item": "Celery", "price": 2.99, "unit": "ea",
            "price_kind": "multibuy", "multibuy_qty": 2,
            "category": "fruits",
        }], [], {})
        self.assertEqual(results[0].multibuy_note,
                         "multi buy 2 for $2.99 — $1.50/ea")


if __name__ == "__main__":
    unittest.main()


class _TabGrid:
    """Minimal Local_Deals worksheet stand-in (grid + batch update)."""

    def __init__(self, grid):
        self.grid = grid

    def get_all_values(self):
        return [list(r) for r in self.grid]

    def clear(self):
        pass

    def freeze(self, rows=1):
        pass

    def update(self, values, range_name):
        self.grid = values


class TestTabDedupWordOrder(unittest.TestCase):
    """FIX-8 (D4): word-order-insensitive row merging in the
    Local_Deals tab. Live symptom: post said '5kg Bag Washed
    Potatoes' while the tab row was 'Washed Potatoes 5kg Bag' ->
    ingest APPENDED a second row instead of merging."""

    def _tab(self, *item_rows):
        grid = [
            ["Product", "Dunya perm (site)", "Dunya special (FB)",
             "Merjan perm", "Merjan special", "Fruitopia perm",
             "Fruitopia special", "Abu Salim perm",
             "Abu Salim special", "Comments"],
            ["Prices valid until", "", "", "", "", "", "", "", "",
             ""],
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
        ]
        grid.extend(item_rows)
        return _TabGrid(grid)

    def test_word_order_variant_merges_newest_price_wins(self):
        ws = self._tab(["Washed Potatoes 5kg Bag", "", "", "", "",
                        "", "3.50 (till 11 Sep)", "", "", ""])
        ld.merge_store_tab(ws, "fruitopia", [{
            "item": "5kg Bag Washed Potatoes", "price": 2.99,
            "unit": "ea", "price_kind": "single", "category": "fruits",
        }])
        grid = ws.get_all_values()
        potatoes = [r for r in grid
                    if "potato" in str(r[0]).lower()]
        self.assertEqual(len(potatoes), 1)        # ONE row, merged
        self.assertEqual(potatoes[0][0],
                         "Washed Potatoes 5kg Bag")  # name kept
        self.assertEqual(potatoes[0][6], 2.99)     # newest price wins

    def test_royal_gala_stays_apart_from_generic_apples(self):
        ws = self._tab(["Apples", "", "", "", "", "", "4.50", "",
                        "", ""])
        ld.merge_store_tab(ws, "fruitopia", [{
            "item": "Royal Gala Apples", "price": 3.90,
            "unit": "ea", "price_kind": "single", "category": "fruits",
        }])
        grid = ws.get_all_values()
        apple_rows = [r for r in grid
                      if "apple" in str(r[0]).lower()]
        self.assertEqual(len(apple_rows), 2)      # variety stays apart
        names = {r[0] for r in apple_rows}
        self.assertIn("Apples", names)
        self.assertIn("Royal Gala Apples /ea", names)

    def test_unit_suffix_rows_merge_with_plain_names(self):
        # Real tab rows carry ' /ea' suffixes — the base-name key
        # strips them, so 'Cos Lettuce' merges into 'Cos Lettuce /ea'.
        ws = self._tab(["Cos Lettuce /ea", "", "", "", "", "",
                        "0.99", "", "", ""])
        ld.merge_store_tab(ws, "fruitopia", [{
            "item": "Cos Lettuce", "price": 1.29,
            "unit": "ea", "price_kind": "single", "category": "fruits",
        }])
        grid = ws.get_all_values()
        lettuce = [r for r in grid if "lettuce" in str(r[0]).lower()]
        self.assertEqual(len(lettuce), 1)
        self.assertEqual(lettuce[0][6], 1.29)


class TestCommentLifecycleRound1(unittest.TestCase):
    """Round-1 audit pins: no path orphans a shop-tagged comment."""

    def test_manual_reprice_without_note_clears_segment(self):
        # A4: plain --set-special over a multibuy cell -> the [FRU]
        # promo segment must die with the old price.
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        ld.set_store_prices(ws, "fruitopia", "special",
                            [{"item": "Carrots", "price": 0.60,
                              "unit": "ea"}])
        grid = ws.get_all_values()
        self.assertEqual(str(grid[3][6]), "0.6")
        self.assertEqual(grid[3][9], "")

    def test_manual_reprice_with_note_replaces_segment(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        ld.set_store_prices(ws, "fruitopia", "special",
                            [{"item": "Carrots", "price": 0.60,
                              "unit": "ea", "note": "3 for $1.80"}])
        self.assertEqual(
            ws.get_all_values()[3][9], "[FRU] 3 for $1.80")

    def test_manual_new_row_note_still_tags_shop(self):
        ws = _v2_ws([["FRUITS", "", "", "", "", "", "", "", "", ""]])
        ld.set_store_prices(ws, "fruitopia", "special",
                            [{"item": "Celery", "price": 1.20,
                              "unit": "ea", "note": "fresh cut"}])
        self.assertEqual(
            ws.get_all_values()[3][9], "[FRU] fresh cut")

    def test_merge_plain_reprice_clears_segment(self):
        # A2 merge-level pin (FIX-4 was parser-level tested).
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        ld.merge_store_tab(ws, "fruitopia", [
            {"item": "Carrots", "category": "fruits",
             "price_kind": "single", "price": 0.6, "unit": "ea"}])
        grid = ws.get_all_values()
        row = next(r for r in grid if str(r[0]).startswith("Carrots"))
        self.assertEqual(str(row[6]), "0.6")
        self.assertEqual(row[9], "")

    def test_merge_dropped_item_keeps_cell_and_comment_together(self):
        # A3 design pin: a post that no longer lists the item leaves
        # cell AND comment TOGETHER (board rotation never deletes;
        # the sweep clears the pair later — test_expired_cell_…).
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", "",
             "0.75 (till 12 Sep)", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        ld.merge_store_tab(ws, "fruitopia", [
            {"item": "Apples", "category": "fruits",
             "price_kind": "single", "price": 2.5, "unit": "kg"}])
        row = next(r for r in ws.get_all_values()
                   if str(r[0]).startswith("Carrots"))
        self.assertEqual(row[6], "0.75 (till 12 Sep)")
        self.assertIn("[FRU]", row[9])

    def test_repair_strips_orphan_segments(self):
        # A7: the live residue shape (rows 115/116) — empty FRU cells.
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Celery /ea", "", "", "", "", "", "", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
            ["Carrots 1kg Bag /ea", "", "", "", "", "", "", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        lines = ld.repair_orphan_comments(ws)
        self.assertEqual(len(lines), 2)
        grid = ws.get_all_values()
        self.assertEqual(grid[3][9], "")
        self.assertEqual(grid[4][9], "")
        self.assertEqual(grid[3][0], "Celery /ea")   # row KEPT
        self.assertEqual(ld.repair_orphan_comments(ws), [])  # idem.

    def test_repair_keeps_segment_when_shop_priced(self):
        ws = _v2_ws([
            ["Carrots /ea", "", "", "", "", 6.50, "", "", "",
             "[FRU] multi buy 2 for $1.50 — $0.75/ea"],
        ])
        self.assertEqual(ld.repair_orphan_comments(ws), [])
        self.assertIn("[FRU]", ws.get_all_values()[2][9])

    def test_repair_preserves_untagged_text_and_other_shops(self):
        ws = _v2_ws([
            ["Carrots /ea", "", "", "", "", 6.50, "", "", "",
             "[FRU] note; loose text; [MER] orphan note"],
        ])
        lines = ld.repair_orphan_comments(ws)
        self.assertEqual(len(lines), 1)          # only MER stripped
        self.assertEqual(ws.get_all_values()[2][9],
                         "[FRU] note; loose text")

    def test_repair_no_tags_writes_nothing(self):
        ws = _v2_ws([
            ["FRUITS", "", "", "", "", "", "", "", "", ""],
            ["Carrots /ea", "", "", "", "", 6.50, "", "", "",
             "loose text only"],
        ])
        self.assertEqual(ld.repair_orphan_comments(ws), [])
        self.assertEqual(ws.clear_calls, 0)
