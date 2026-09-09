"""T-set 1 — the `live` verb (spec §7/§8, §15): no-write guarantee,
≤3/store cap, provider iteration order, side-note presence, store-error
degradation. Offline (fake ProductItems; no network, no sheet)."""
from __future__ import annotations
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_HERE = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from extractors.models import ProductItem          # noqa: E402
from core.v2_live import (                         # noqa: E402
    LIVE_PROVIDERS, live_search, render_live,
)


def _items(*names_prices, store="woolworths"):
    out = []
    for i, (name, price) in enumerate(names_prices):
        out.append(ProductItem(store=store, raw_name=name, price=price,
                               size=f"{i + 1}kg"))
    return out


class TestNoWriteGuarantee(unittest.TestCase):
    """Spec §7: the live verb NEVER writes — the module cannot even
    receive a worksheet handle."""

    def test_no_sheet_args_in_signatures(self):
        import core.v2_live as mod
        for name, fn in vars(mod).items():
            if not callable(fn) or getattr(fn, "__module__", "") != \
                    mod.__name__ or name.startswith("_"):
                continue
            for param in inspect.signature(fn).parameters:
                self.assertNotIn("sheet", param.lower(),
                                 f"{name}({param})")
                self.assertNotIn("worksheet", param.lower(),
                                 f"{name}({param})")
                self.assertNotIn("ws", param.lower(),
                                 f"{name}({param})")

    def test_module_imports_no_sheets_client(self):
        import core.v2_live as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        for banned in ("sheets_client", "connect_spreadsheet",
                       "connect_worksheet", "get_all_values",
                       "worksheet("):
            self.assertNotIn(banned, source)


class TestSearchSemantics(unittest.TestCase):
    def test_provider_list_order(self):
        """§15: the provider list IS [woolworths, coles]; adding a
        store later is one entry + one extractor mapping."""
        self.assertEqual(LIVE_PROVIDERS, ["woolworths", "coles"])

    def test_iteration_order_and_shape(self):
        order: list = []

        def _ww(query, page_size=10):
            order.append("woolworths")
            return _items(("Wool Boneless Chicken Breast", 11.5))

        def _coles(query, page_size=10):
            order.append("coles")
            return _items(("Coles Chicken Breast Schnitzel", 9.0),
                          store="coles")

        with patch("extractors.woolworths_extractor."
                   "fetch_woolworths_search_noauth",
                   side_effect=_ww), \
             patch("extractors.coles_extractor.fetch_coles_search",
                   side_effect=_coles):
            results = live_search("chicken breast")
        # iteration order: woolworths ran first
        self.assertEqual(order, ["woolworths", "coles"])
        self.assertEqual(results["woolworths"][0]["price"], 11.5)
        self.assertEqual(results["coles"][0]["name"],
                         "Coles Chicken Breast Schnitzel")
        for provider in LIVE_PROVIDERS:
            for hit in results[provider]:
                self.assertEqual(
                    sorted(hit), ["name", "price", "size"])

    def test_cap_three_per_store(self):
        items = _items(*tuple((f"Product Number {i}", 1.0 + i)
                              for i in range(10)))
        with patch("extractors.woolworths_extractor."
                   "fetch_woolworths_search_noauth",
                   return_value=items), \
             patch("extractors.coles_extractor.fetch_coles_search",
                   return_value=[]):
            results = live_search("product")
        self.assertEqual(len(results["woolworths"]), 3)

    def test_ranking_prefers_term_matches(self):
        items = _items(("Dog Food Deluxe Mix", 13.0),
                       ("Chicken Breast Fillet", 11.0),
                       ("Chicken Stock Cube", 2.0))
        with patch("extractors.woolworths_extractor."
                   "fetch_woolworths_search_noauth",
                   return_value=items), \
             patch("extractors.coles_extractor.fetch_coles_search",
                   return_value=[]):
            results = live_search("chicken breast")
        self.assertEqual(results["woolworths"][0]["name"],
                         "Chicken Breast Fillet")

    def test_nonpositive_price_dropped(self):
        items = _items(("Free Sample Pack", 0.0),
                       ("Real Product", 4.0))
        with patch("extractors.woolworths_extractor."
                   "fetch_woolworths_search_noauth",
                   return_value=items), \
             patch("extractors.coles_extractor.fetch_coles_search",
                   return_value=[]):
            results = live_search("real product")
        self.assertEqual([h["name"] for h in results["woolworths"]],
                         ["Real Product"])

    def test_store_error_degrades_to_errors_entry(self):
        with patch("extractors.woolworths_extractor."
                   "fetch_woolworths_search_noauth",
                   return_value=_items(("Wool Product", 3.0))), \
             patch("extractors.coles_extractor.fetch_coles_search",
                   side_effect=RuntimeError("breaker open")):
            results = live_search("product")
        self.assertEqual(results["errors"],
                         {"coles": "RuntimeError"})
        self.assertEqual(results["coles"], [])
        self.assertEqual(len(results["woolworths"]), 1)


class TestRender(unittest.TestCase):
    def test_render_stores_and_lines(self):
        results = {
            "woolworths": [{"name": "Wool Breast 1kg", "price": 11.5,
                            "size": "1kg"}],
            "coles": [],
            "errors": {},
        }
        out = render_live(results, None)
        self.assertIn("🟢 Woolworths", out)
        self.assertIn("🔴 Coles", out)
        self.assertIn("$11.50", out)
        self.assertIn("· 1kg", out)
        self.assertIn("no results", out)
        self.assertNotIn("ℹ️", out)

    def test_render_side_note_when_tracked(self):
        results = {"woolworths": [], "coles": [], "errors": {}}
        out = render_live(results, "Your sheet: $8.50 (display price)")
        self.assertIn("ℹ️ Your sheet: $8.50 (display price)", out)

    def test_render_error_degradation_line(self):
        results = {"woolworths": [], "coles": [],
                   "errors": {"coles": "RuntimeError"}}
        out = render_live(results, None)
        self.assertIn("⚠️", out)
        self.assertIn("Coles search unavailable (RuntimeError)", out)


if __name__ == "__main__":
    unittest.main()
