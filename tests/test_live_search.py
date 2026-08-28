#!/usr/bin/env python3
"""GROUP B — 10 integration tests for Woolworths (curl_cffi) + Coles (Scrape.do)
live search, mocked.

No network, no real APIs. Mocks both extractor functions in every test since
LookupEngine._live_search calls both stores. Verifies the integration layer:
results composition, error handling, and edge cases.

Usage:
    python grocery-price-tracker/tests/test_live_search.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Bootstrap sys.path so core/ and extractors/ are importable
_HERE = Path(__file__).resolve().parent  # tests/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from core.lookup import LookupEngine, LookupStatus
from extractors.models import ProductItem

# Shortcut module paths for patching
_WW_NOAUTH = "extractors.woolworths_extractor.fetch_woolworths_search_noauth"
_COLES = "extractors.coles_extractor.fetch_coles_search"


def _make_item(store: str, name: str, price: float, *,
               is_special: bool = False,
               special_desc: str = "") -> ProductItem:
    """Create a ProductItem for test stubs."""
    return ProductItem(
        store=store,
        raw_name=name,
        price=price,
        is_special=is_special,
        special_desc=special_desc,
    )


def _make_engine():
    """Create a bare LookupEngine with no worksheet/index (lazy)."""
    engine = LookupEngine.__new__(LookupEngine)
    engine._worksheet = None
    engine._index = None
    return engine


class TestWoolworthsNoauthSearch(unittest.TestCase):
    """5 tests for Woolworths curl_cffi no-auth search integration."""

    def test_noauth_returns_products(self):
        """fetch_woolworths_search_noauth returns ProductItem list."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: [
            _make_item("woolworths", "WW Milk 2L", 3.50),
        ]), patch(_COLES, side_effect=lambda q, **kw: []):
            results = _make_engine()._live_search("milk")
            self.assertGreater(len(results), 0)
            self.assertEqual(results[0].store, "woolworths")
            self.assertEqual(results[0].price, 3.50)

    def test_noauth_returns_multiple_products(self):
        """Multiple results returned."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: [
            _make_item("woolworths", "WW Milk 2L", 3.50),
            _make_item("woolworths", "WW Milk 1L", 2.50),
            _make_item("woolworths", "WW Milk 3L", 5.00),
        ]), patch(_COLES, side_effect=lambda q, **kw: []):
            results = _make_engine()._live_search("milk")
            self.assertEqual(len(results), 3)

    def test_noauth_returns_empty(self):
        """No results from either store returns empty list."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: []), \
             patch(_COLES, side_effect=lambda q, **kw: []):
            results = _make_engine()._live_search("nonexistent12345")
            self.assertEqual(results, [])

    def test_noauth_exception_handled_gracefully(self):
        """Exception from Woolworths noauth is caught, doesn't crash."""
        with patch(_WW_NOAUTH, side_effect=RuntimeError("curl_cffi TLS")), \
             patch(_COLES, side_effect=lambda q, **kw: []):
            results = _make_engine()._live_search("milk")
            self.assertEqual(results, [])

    def test_noauth_special_products(self):
        """Products with special_desc are included."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: [
            _make_item("woolworths", "WW Milk 2L", 3.50,
                       is_special=True, special_desc="Half Price"),
        ]), patch(_COLES, side_effect=lambda q, **kw: []):
            results = _make_engine()._live_search("milk")
            self.assertTrue(results[0].is_special)
            self.assertEqual(results[0].special_desc, "Half Price")


class TestColesScrapeDoSearch(unittest.TestCase):
    """3 tests for Coles Scrape.do search integration."""

    def test_coles_returns_products(self):
        """fetch_coles_search via Scrape.do returns ProductItem list."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: []), \
             patch(_COLES, side_effect=lambda q, **kw: [
            _make_item("coles", "Coles Milk 2L", 3.30),
        ]):
            results = _make_engine()._live_search("milk")
            self.assertGreater(len(results), 0)
            self.assertEqual(results[0].store, "coles")
            self.assertEqual(results[0].price, 3.30)

    def test_coles_returns_empty(self):
        """No results from Coles returns empty (Woolworths also empty)."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: []), \
             patch(_COLES, side_effect=lambda q, **kw: []):
            results = _make_engine()._live_search("nonexistent")
            self.assertEqual(results, [])

    def test_coles_exception_handled_gracefully(self):
        """Exception from Coles Scrape.do is caught, doesn't crash."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: []), \
             patch(_COLES, side_effect=RuntimeError("Scrape.do quota")):
            results = _make_engine()._live_search("milk")
            self.assertEqual(results, [])


class TestCombinedLiveSearch(unittest.TestCase):
    """2 tests for combined Woolworths + Coles live search."""

    def test_both_stores_return_results(self):
        """Both stores return results — all items in combined list."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: [
            _make_item("woolworths", "WW Milk 2L", 3.50),
            _make_item("woolworths", "WW Milk 1L", 2.50),
        ]), patch(_COLES, side_effect=lambda q, **kw: [
            _make_item("coles", "Coles Milk 2L", 3.30),
        ]):
            results = _make_engine()._live_search("milk")
            self.assertEqual(len(results), 3)  # 2 WW + 1 Coles
            stores = {r.store for r in results}
            self.assertIn("woolworths", stores)
            self.assertIn("coles", stores)

    def test_one_store_works_other_fails(self):
        """Woolworths works, Coles fails — partial results returned."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: [
            _make_item("woolworths", "WW Milk 2L", 3.50),
        ]), patch(_COLES, side_effect=RuntimeError("Scrape.do 401")):
            results = _make_engine()._live_search("milk")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].store, "woolworths")


class TestLiveSearchEdgeCases(unittest.TestCase):
    """Edge case tests for live search integration."""

    def test_empty_query_returns_empty(self):
        """Empty query string returns empty list immediately."""
        results = _make_engine()._live_search("")
        self.assertEqual(results, [])

    def test_whitespace_only_query_returns_empty(self):
        """Whitespace-only query returns empty list."""
        results = _make_engine()._live_search("   ")
        self.assertEqual(results, [])

    def test_live_search_preserves_price_order(self):
        """Results preserve the order: Woolworths first, then Coles."""
        with patch(_WW_NOAUTH, side_effect=lambda q, **kw: [
            _make_item("woolworths", "A", 1.0),
            _make_item("woolworths", "B", 2.0),
        ]), patch(_COLES, side_effect=lambda q, **kw: [
            _make_item("coles", "C", 3.0),
            _make_item("coles", "D", 4.0),
        ]):
            results = _make_engine()._live_search("test")
            self.assertEqual(results[0].store, "woolworths")
            self.assertEqual(results[1].store, "woolworths")
            self.assertEqual(results[2].store, "coles")
            self.assertEqual(results[3].store, "coles")


if __name__ == "__main__":
    unittest.main()
