"""Aldi extractor (spec §3.1): mapping, guards, retry, pagination.
Offline — fixtures + patched _aldi_get/_request; no network, no sheet."""
from __future__ import annotations
import json, sys, unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors.models import ProductItem
from extractors import aldi_extractor as ax

FIX = _HERE / "fixtures" / "aldi"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class TestMapping(unittest.TestCase):
    def test_fixture_mapping_fields(self):
        items = [ax._to_product_item(p)
                 for p in _load("search_milk.json")["data"]]
        items = [i for i in items if i is not None]
        by = {i.raw_name: i for i in items}
        self.assertEqual(by["Light Milk 2L"].price, 3.39)
        self.assertEqual(by["Light Milk 2L"].brand, "FARMDALE")
        self.assertEqual(by["Light Milk 2L"].size, "2 L")
        self.assertEqual(by["Light Milk 2L"].unit_price,
                         "$1.70 per 1 L")
        self.assertEqual(by["Light Milk 2L"].product_id,
                         "000000000000398691")
        self.assertEqual(by["Light Milk 2L"].store, "aldi")

    def test_zero_price_item_dropped(self):
        self.assertIsNone(
            ax._to_product_item(_load("search_milk.json")["data"][4]))

    def test_notforsale_kept(self):
        item = ax._to_product_item(_load("search_milk.json")["data"][0])
        self.assertIsNotNone(item)
        self.assertEqual(item.price, 3.99)

    def test_special_flags_from_was_price(self):
        item = ax._to_product_item(_load("search_milk.json")["data"][2])
        self.assertTrue(item.is_special)
        self.assertEqual(item.special_desc, "Save $0.34")

    def test_missing_brand_becomes_empty(self):
        # the fixture's brandless item is the zero-price one; use a dict
        item = ax._to_product_item({"name": "Kanzi Apples Loose",
                                    "brandName": None,
                                    "price": {"amount": 131}})
        self.assertEqual(item.brand, "")


class TestFetch(unittest.TestCase):
    def test_fetch_aldi_search_maps_and_skips(self):
        with patch.object(ax, "_aldi_get",
                          return_value=_load("search_milk.json")):
            items = ax.fetch_aldi_search("milk", page_size=5)
        self.assertEqual(len(items), 4)      # zero-price dropped

    def test_retry_once_on_403(self):
        calls = {"n": 0}

        class _Resp:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload

            def json(self):
                return self._payload

        def _flaky(path, params):
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(403, {})
            return _Resp(200, _load("search_milk.json"))

        with patch.object(ax, "_request", side_effect=_flaky), \
             patch.object(ax.time, "sleep") as slept:
            items = ax.fetch_aldi_search("milk")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(len(items), 4)
        slept.assert_called_once()

    def test_aldi_get_raises_after_retries(self):
        with patch.object(ax, "_request",
                          side_effect=RuntimeError("net down")), \
             patch.object(ax.time, "sleep"):
            with self.assertRaises(ax.AldiAPIError):
                ax._aldi_get("/v3/product-search", {"q": "milk"})

    def test_find_promotion_by_exact_date(self):
        with patch.object(ax, "_aldi_get",
                          return_value=_load("promotion_tree.json")):
            self.assertEqual(
                ax.find_promotion("2026-09-12")["title"],
                "Available from Sat 12th September")
            self.assertIsNone(ax.find_promotion("2026-09-11"))

    def test_specials_pagination_stops_on_short_page(self):
        # Page 1 is a FULL 30-row page (the stop rule is
        # len(rows) < limit=30), so the fetcher must continue to the
        # short page 2 and stop there — the multi-page proof.
        def _row(n):
            return {"name": f"Bulk Item {n:02d}", "brandName": "B",
                    "sellingSize": None, "sku": f"s{n}",
                    "notForSale": False, "categories": [], "assets": [],
                    "price": {"amount": 100 + n}}

        last = {"name": "Last Item", "brandName": "B",
                "sellingSize": None, "sku": "s2",
                "notForSale": False,
                "categories": [], "assets": [],
                "price": {"amount": 100}}
        pages = [{"data": [_row(i) for i in range(30)]},
                 {"data": [last]}]

        def _fake(path, params):
            self.assertEqual(path, "/v3/product-search")
            self.assertEqual(params["promotionKey"], "2026-09-09")
            return pages[params["offset"] // 30]

        with patch.object(ax, "_aldi_get", side_effect=_fake):
            items = ax.fetch_aldi_specials("2026-09-09")
        self.assertEqual(len(items), 31)

    def test_no_scrapedo_dependency(self):
        source = Path(ax.__file__).read_text(encoding="utf-8")
        for banned in ("scrapedo", "SCRAPEDO", "zenrows", "ZENROWS"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
