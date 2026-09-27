"""No-duplicate-row guarantees for bundle rows (user ask 2026-09-27:
'so if after 5 weeks again merjan comes back with the special Halal
Chicken Thigh Fillet – (2kg) /ea (it might be different wordings) -
can you make sure there is no different lines created').

Every merge runs through the REAL pipeline pieces: the pack-guard
(the deal arrives typed 'single' with only its verbatim tile text —
the worst observed model run), the halal prefixer, the display-name
builder and the live-grid reuse matcher. Row-count assertions prove
ONE row per (base item, pack size/count) no matter the wording, the
shop, or how many weeks pass.
"""
from __future__ import annotations

import unittest

from extractors.deal_text import normalise_pack_deal
from core import local_deals as ld


class FakeSheet:
    """Minimal worksheet for merge_store_tab (no master mirror)."""

    def __init__(self, rows=None):
        self.rows = [r[:] for r in (rows or [])]

    def get_all_values(self):
        return [r[:] for r in self.rows]

    def update(self, values=None, range_name=None, **kw):
        self.rows = [r[:] for r in values]

    def clear(self):
        self.rows = []

    def freeze(self, rows=0):
        pass


def _board_deal(item, raw, price, unit="kg"):
    """A tile as the vision model types it on a BAD day: price_kind
    'single', quantity only in raw_text — the guard must recover."""
    return normalise_pack_deal({
        "item": item, "raw_text": raw, "price": price,
        "unit": unit, "price_kind": "single", "multibuy_qty": None,
        "bulk_size": None, "category": "butchery", "notes": ""})


def _merge(ws, store, deals):
    deals = ld._prefix_butcher_deals(store, deals)
    for d in deals:
        d["valid_until"] = None
    ld.merge_store_tab(ws, store, deals)


def _names(ws):
    return [str(r[0]) for r in ws.get_all_values()[1:]]


def _pack_rows(ws, base):
    return [n for n in _names(ws)
            if base.lower() in n.lower()
            and ("\u2013 (" in n)]


class TestKgBundleNoDuplicates(unittest.TestCase):
    """The SAME 2kg thigh-fillet deal returning week after week in
    every wording the shop has ever used — ONE row, always."""

    def _seed(self):
        ws = FakeSheet([["Product"] + [c for _k, c in ld.TAB_COLUMNS],
                        ["Halal Chicken Thigh Fillet /kg"]
                        + [""] * len(ld.TAB_COLUMNS)])
        _merge(ws, "merjan", [_board_deal(
            "Chicken Thigh Fillet",
            "2KG CHICKEN THIGH FILLET $21.99", 21.99)])
        self.assertEqual(
            _pack_rows(ws, "Thigh Fillet"),
            ["Halal Chicken Thigh Fillet \u2013 (2kg) /ea"])
        return ws

    def test_week2_same_wording_new_price_reuses(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Chicken Thigh Fillet",
            "2KG CHICKEN THIGH FILLET $23.49", 23.49)])
        self.assertEqual(_pack_rows(ws, "Thigh Fillet"),
                         ["Halal Chicken Thigh Fillet \u2013 (2kg) /ea"])
        row = next(r for r in ws.get_all_values()
                   if "\u2013 (2kg)" in str(r[0]))
        self.assertEqual(row[5], 23.49)      # cell updated, not duped

    def test_week3_shorter_name_reuses(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Thigh Fillet", "2 KG THIGH FILLET $21.99", 21.99)])
        self.assertEqual(
            len(_pack_rows(ws, "Thigh Fillet")), 1)

    def test_week4_quantity_mid_line_reuses(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Chicken Thigh Fillet",
            "CHICKEN THIGH FILLET 2KG FOR $23.49", 23.49)])
        self.assertEqual(
            len(_pack_rows(ws, "Thigh Fillet")), 1)

    def test_week5_min_wording_reuses(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Chicken Thigh Fillet",
            "CHICKEN THIGH FILLET MIN 2KG $22.99", 22.99)])
        self.assertEqual(
            len(_pack_rows(ws, "Thigh Fillet")), 1)

    def test_other_shop_same_pack_shares_the_row(self):
        ws = self._seed()
        _merge(ws, "dunya_fb", [_board_deal(
            "Chicken Thigh Fillet",
            "2KG CHICKEN THIGH FILLET $19.99", 19.99)])
        self.assertEqual(
            len(_pack_rows(ws, "Thigh Fillet")), 1)
        row = next(r for r in ws.get_all_values()
                   if "\u2013 (2kg)" in str(r[0]))
        self.assertEqual(row[5], 21.99)      # merjan cell untouched
        self.assertEqual(row[3], 19.99)      # dunya FB special
        self.assertIn("[MER]", row[11])
        self.assertIn("[DUN]", row[11])

    def test_different_size_is_a_new_row_by_design(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Chicken Thigh Fillet",
            "3KG CHICKEN THIGH FILLET $29.99", 29.99)])
        pack_rows = _pack_rows(ws, "Thigh Fillet")
        self.assertEqual(len(pack_rows), 2)
        self.assertIn("Halal Chicken Thigh Fillet \u2013 (3kg) /ea",
                      pack_rows)

    def test_plain_per_kg_deal_never_lands_on_the_pack_row(self):
        ws = self._seed()
        _merge(ws, "merjan", [{
            "item": "Chicken Thigh Fillet", "raw_text": "X",
            "price": 17.99, "unit": "kg", "price_kind": "single",
            "multibuy_qty": None, "bulk_size": None,
            "category": "butchery", "notes": "", "valid_until": None}])
        kg_row = next(r for r in ws.get_all_values()
                      if str(r[0]) == "Halal Chicken Thigh Fillet /kg")
        self.assertEqual(kg_row[5], 17.99)
        self.assertEqual(
            len(_pack_rows(ws, "Thigh Fillet")), 1)


class TestCountedBundleNoDuplicates(unittest.TestCase):
    """'2 steamer chickens for $11.99' in every wording — ONE '(2
    pack)' row, separate from the plain /ea row (user directive
    2026-09-27: separate lines)."""

    def _seed(self):
        ws = FakeSheet([["Product"] + [c for _k, c in ld.TAB_COLUMNS],
                        ["Halal Steamer Chickens /ea"]
                        + [""] * len(ld.TAB_COLUMNS)])
        _merge(ws, "merjan", [_board_deal(
            "Steamer Chickens", "2 STEAMER CHICKENS $11.99",
            11.99, unit="ea")])
        self.assertEqual(
            _pack_rows(ws, "Steamer"),
            ["Halal Steamer Chickens \u2013 (2 pack) /ea"])
        return ws

    def test_count_prefix_new_price_reuses(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Steamer Chickens", "2 STEAMER CHICKENS $12.49",
            12.49, unit="ea")])
        self.assertEqual(
            len(_pack_rows(ws, "Steamer")), 1)

    def test_for_suffix_wording_reuses(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Steamer Chickens", "STEAMER CHICKENS 2 FOR $12.49",
            12.49, unit="ea")])
        self.assertEqual(
            len(_pack_rows(ws, "Steamer")), 1)

    def test_pack_wording_reuses(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Steamer Chickens", "2 PACK STEAMER CHICKENS $12.49",
            12.49, unit="ea")])
        self.assertEqual(
            len(_pack_rows(ws, "Steamer")), 1)

    def test_plain_per_ea_price_stays_on_the_plain_row(self):
        ws = self._seed()
        _merge(ws, "merjan", [{
            "item": "Steamer Chickens", "raw_text": "X",
            "price": 8.99, "unit": "ea", "price_kind": "single",
            "multibuy_qty": None, "bulk_size": None,
            "category": "butchery", "notes": "", "valid_until": None}])
        plain = next(r for r in ws.get_all_values()
                     if str(r[0]) == "Halal Steamer Chickens /ea")
        self.assertEqual(plain[5], 8.99)
        self.assertEqual(
            len(_pack_rows(ws, "Steamer")), 1)

    def test_different_count_is_a_new_row(self):
        ws = self._seed()
        _merge(ws, "merjan", [_board_deal(
            "Steamer Chickens", "3 STEAMER CHICKENS $16.99",
            16.99, unit="ea")])
        self.assertEqual(
            len(_pack_rows(ws, "Steamer")), 2)


class TestOcrQtyFlipGuard(unittest.TestCase):
    """2026-09-27 drumettes incident: one run read the tile 5KG, the
    next 2KG - both passes of the second run agreed on the wrong
    number and minted a duplicate '(2kg)' row at the same price. The
    merge now adopts the existing row's qty when the bundle TOTAL
    matches this shop's ACTIVE special on a same-family pack row."""

    def test_same_price_different_size_adopts_existing(self):
        ws = FakeSheet([["Product"] + [c for _k, c in ld.TAB_COLUMNS],
                        ["Halal Chicken Drumettes /kg"]
                        + [""] * len(ld.TAB_COLUMNS),
                        ["Halal Chicken Drumettes \u2013 (5kg) /ea"]
                        + [""] * len(ld.TAB_COLUMNS)])
        rows = ws.get_all_values()
        rows[2][5] = "19.99 (till 27 Sep)"
        ws.rows = rows
        _merge(ws, "merjan", [{
            "item": "Chicken Drumettes",
            "raw_text": "2KG CHICKEN DRUMETTES $19.99",
            "price": 19.99, "unit": "kg", "price_kind": "multibuy",
            "multibuy_qty": 2, "bulk_size": None,
            "category": "butchery", "notes": "",
            "valid_until": None}])
        names = _names(ws)
        self.assertEqual(len(names), 2, names)   # NO (2kg) row
        row = next(r for r in ws.get_all_values()
                   if "(5kg)" in str(r[0]))
        self.assertIn("multi buy 5kg", row[11])

    def test_different_price_mints_the_new_size(self):
        """A genuinely different deal (new price) still creates its
        own row - the guard only fires on identical totals."""
        ws = FakeSheet([["Product"] + [c for _k, c in ld.TAB_COLUMNS],
                        ["Halal Chicken Drumettes \u2013 (5kg) /ea"]
                        + [""] * len(ld.TAB_COLUMNS)])
        rows = ws.get_all_values()
        rows[1][5] = "19.99 (till 27 Sep)"
        ws.rows = rows
        _merge(ws, "merjan", [{
            "item": "Chicken Drumettes",
            "raw_text": "2KG CHICKEN DRUMETTES $15.99",
            "price": 15.99, "unit": "kg", "price_kind": "multibuy",
            "multibuy_qty": 2, "bulk_size": None,
            "category": "butchery", "notes": "",
            "valid_until": None}])
        self.assertEqual(len(_names(ws)), 2)


class TestWeekendBoardValidity(unittest.TestCase):
    """User ask 2026-09-27: 'why does merjan always ask me to enter
    the end date when it is clearly mentioned on their pic weekend
    only' - the WEEKEND phrase is on the IMAGE; the sweep's vision
    path now applies the same weekend rule as text posts (ends the
    coming Sunday, user directive 2026-09-22)."""

    def test_vision_weekend_board_ends_sunday(self):
        from datetime import date  # noqa: F401
        from unittest.mock import patch
        from pathlib import Path
        from core import local_deals as ld2

        class _P:
            text = ""
            image_urls = ["x"]
            post_ref = "p1"

        payload = {"valid_until": None,
                   "validity_text": "WEEKEND SPECIALS",
                   "deals": [_board_deal("Thigh Fillet",
                                         "2KG THIGH FILLET $21.99",
                                         21.99)]}
        with patch("core.flyer_vision.parse_board_images",
                          return_value=payload), \
             patch("extractors.fb_timeline_fetch."
                   "download_post_images",
                   return_value=[Path("x.jpg")]):
            deals, source, until = ld2.extract_post_deals(
                _P(), Path("."), "merjan")
        self.assertEqual(source, "vision")
        self.assertEqual(len(deals), 1)
        self.assertIsNotNone(until)      # weekend rule fired
        self.assertEqual(until.weekday(), 6)   # a Sunday

    def test_dated_board_not_overridden(self):
        from unittest.mock import patch
        from pathlib import Path
        from core import local_deals as ld2

        class _P:
            text = ""
            image_urls = ["x"]
            post_ref = "p1"

        payload = {"valid_until": "2026-10-02",
                   "validity_text": "valid until 02/10/2026",
                   "deals": []}
        with patch("core.flyer_vision.parse_board_images",
                          return_value=payload), \
             patch("extractors.fb_timeline_fetch."
                   "download_post_images",
                   return_value=[Path("x.jpg")]):
            _deals, _src, until = ld2.extract_post_deals(
                _P(), Path("."), "merjan")
        self.assertEqual(str(until), "2026-10-02")


class TestWholeChickensCountedBundle(unittest.TestCase):
    """'5 whole chickens for $34.99' — its own row, separate from the
    s9/s14 per-bird rows and from any '(min 1.9kg)' size-spec deal."""

    def test_five_for_gets_own_row(self):
        ws = FakeSheet([["Product"] + [c for _k, c in ld.TAB_COLUMNS],
                        ["Halal Whole chicken s14 /ea"]
                        + [""] * len(ld.TAB_COLUMNS)])
        _merge(ws, "merjan", [_board_deal(
            "Whole Chickens", "WHOLE CHICKENS 5 FOR $34.99",
            34.99, unit="ea")])
        pack = [n for n in _names(ws) if "(5 pack)" in n]
        self.assertEqual(
            pack, ["Halal Whole Chickens \u2013 (5 pack) /ea"])
        # the per-bird row is untouched
        s14 = next(r for r in ws.get_all_values()
                   if str(r[0]) == "Halal Whole chicken s14 /ea")
        self.assertEqual(s14[5], "")

    def test_min_weight_size_spec_stays_per_bird(self):
        ws = FakeSheet([["Product"] + [c for _k, c in ld.TAB_COLUMNS],
                        ["Halal Whole chicken s14 /ea"]
                        + [""] * len(ld.TAB_COLUMNS)])
        _merge(ws, "merjan", [_board_deal(
            "Whole Chicken", "WHOLE CHICKEN (MIN 1.9KG) $34.99",
            34.99, unit="ea")])
        self.assertEqual(_pack_rows(ws, "Whole"), [])
        s14 = next(r for r in ws.get_all_values()
                   if str(r[0]) == "Halal Whole chicken s14 /ea")
        self.assertEqual(s14[5], 34.99)


if __name__ == "__main__":
    unittest.main()
