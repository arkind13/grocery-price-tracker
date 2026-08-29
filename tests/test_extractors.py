#!/usr/bin/env python3
"""Comprehensive unit tests for the extraction engine.

Tests:
  - ``ProductItem`` dataclass construction
  - ``SessionManager`` cookie parsing and header building
  - ``doc_parser`` text/dox parsing
  - ``hub`` store resolution and fallback behaviour
  - ``woolworths_extractor`` API item parsing
  - ``coles_extractor`` API result parsing

Run::
    python tests/test_extractors.py
"""

import os
import sys
import tempfile
import unittest

# Path setup
_HERE = os.path.dirname(os.path.abspath(__file__))
_TRACKER_DIR = os.path.abspath(os.path.join(_HERE, ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_TRACKER_DIR, ".."))
for p in (_TRACKER_DIR, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# =========================================================================
# Test ProductItem
# =========================================================================
class TestProductItem(unittest.TestCase):
    """Tests for the shared ProductItem dataclass."""

    def test_default_construction(self):
        """A ProductItem can be created with just store, name, and price."""
        from extractors.models import ProductItem

        item = ProductItem(store="woolworths", raw_name="Test Milk", price=4.50)
        self.assertEqual(item.store, "woolworths")
        self.assertEqual(item.raw_name, "Test Milk")
        self.assertEqual(item.price, 4.50)
        self.assertFalse(item.is_special)
        self.assertIsInstance(item.timestamp, str)
        self.assertTrue(len(item.timestamp) > 10)

    def test_full_construction(self):
        """A ProductItem can be created with all fields."""
        from extractors.models import ProductItem

        item = ProductItem(
            store="coles",
            raw_name="Coles Full Cream Milk 2L",
            price=3.80,
            is_special=True,
            special_desc="Was $5.00",
            rewards_points="200",
            unit_price="$1.90 / 1L",
            category="Dairy",
            size="2L",
            brand="Coles",
        )
        self.assertEqual(item.store, "coles")
        self.assertTrue(item.is_special)
        self.assertEqual(item.rewards_points, "200")

    def test_to_dict(self):
        """to_dict returns a JSON-serialisable dict."""
        from extractors.models import ProductItem

        item = ProductItem(store="aldi", raw_name="Test Item", price=2.00)
        d = item.to_dict()
        self.assertEqual(d["store"], "aldi")
        self.assertEqual(d["price"], 2.00)
        self.assertIn("timestamp", d)

    def test_to_tuple(self):
        """to_tuple returns 12 elements matching Products_Master columns."""
        from extractors.models import ProductItem

        item = ProductItem(
            store="woolworths",
            raw_name="Test Milk",
            price=4.50,
            category="Dairy",
            size="1L",
            brand="Test Brand",
        )
        t = item.to_tuple()
        self.assertEqual(len(t), 12)
        self.assertEqual(t[0], "Test Milk")   # Product_Name
        self.assertEqual(t[1], "Dairy")        # Category
        self.assertEqual(t[2], "1L")           # Size
        self.assertEqual(t[3], "")             # Woolworths_Price
        self.assertEqual(t[4], "")             # Coles_Price
        self.assertEqual(t[5], "")             # Aldi_Price
        self.assertEqual(t[6], "Test Brand")   # Brand_Type


# =========================================================================
# Test SessionManager
# =========================================================================
class TestSessionManager(unittest.TestCase):
    """Tests for the SessionManager."""

    def setUp(self):
        from extractors.session_manager import SessionManager

        self.sm = SessionManager()

    def test_known_stores(self):
        """SessionManager knows woolworths and coles."""
        self.assertIn("woolworths", self.sm.store_names)
        self.assertIn("coles", self.sm.store_names)

    def test_get_cookies_empty(self):
        """get_cookies returns empty dict when no cookie is set."""
        cookies = self.sm.get_cookies("woolworths")
        self.assertIsInstance(cookies, dict)

    def test_get_headers_no_cookie(self):
        """get_headers returns base headers when no cookie is set.

        Hermetic: WOOLWORTHS_COOKIE may exist in the real environment
        (loaded from the root .env at module import) — temporarily
        remove it so the no-cookie path is actually exercised.
        """
        import os
        old = os.environ.get("WOOLWORTHS_COOKIE", "")
        if old:
            del os.environ["WOOLWORTHS_COOKIE"]
        try:
            headers = self.sm.get_headers("woolworths")
            self.assertIn("User-Agent", headers)
            self.assertIn("Accept", headers)
            self.assertNotIn("Cookie", headers)
        finally:
            if old:
                os.environ["WOOLWORTHS_COOKIE"] = old

    def test_get_headers_with_cookie(self):
        """get_headers includes Cookie header when cookie is set."""
        import os
        # Temporarily set env var
        old = os.environ.get("WOOLWORTHS_COOKIE", "")
        os.environ["WOOLWORTHS_COOKIE"] = "session=abc123; t=xyz"
        try:
            headers = self.sm.get_headers("woolworths")
            self.assertIn("Cookie", headers)
            self.assertEqual(headers["Cookie"], "session=abc123; t=xyz")
        finally:
            if old:
                os.environ["WOOLWORTHS_COOKIE"] = old
            else:
                del os.environ["WOOLWORTHS_COOKIE"]

    def test_unknown_store_raises(self):
        """An unknown store name raises ValueError."""
        with self.assertRaises(ValueError):
            self.sm.get_headers("unknown_store")

    def test_parse_cookie_string(self):
        """_parse_cookie_string correctly splits key=value pairs."""
        from extractors.session_manager import SessionManager

        result = SessionManager._parse_cookie_string("key1=val1; key2=val2")
        self.assertEqual(result, {"key1": "val1", "key2": "val2"})

    def test_summary_structure(self):
        """summary() returns expected keys."""
        s = self.sm.summary()
        self.assertIn("cookies_configured", s)
        self.assertIn("cookies_missing", s)
        self.assertIn("fallback_available", s)
        self.assertIn("session_alive", s)


# =========================================================================
# Test Doc Parser
# =========================================================================
class TestDocParser(unittest.TestCase):
    """Tests for the document/text parser."""

    def test_parse_text_dump_two_line_format(self):
        """Text with name then price on next line is parsed correctly."""
        from extractors.doc_parser import parse_text_dump

        text = "Oatly Barista Milk 1L\n$4.50\nBega Cheese Block 500g\n$7.00\n"
        items = parse_text_dump(text, store="woolworths")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].raw_name, "Oatly Barista Milk 1L")
        self.assertAlmostEqual(items[0].price, 4.50)
        self.assertEqual(items[1].raw_name, "Bega Cheese Block 500g")
        self.assertAlmostEqual(items[1].price, 7.00)

    def test_parse_text_dump_empty(self):
        """Empty text returns empty list."""
        from extractors.doc_parser import parse_text_dump

        items = parse_text_dump("", store="woolworths")
        self.assertEqual(len(items), 0)

    def test_parse_text_dump_single_line_format(self):
        """Text with name - $price on same line is parsed."""
        from extractors.doc_parser import parse_text_dump

        text = "Oatly Barista Milk 1L - $4.50\nBega Cheese 500g - $7.00\n"
        items = parse_text_dump(text, store="coles")
        self.assertEqual(len(items), 2)

    def test_detect_category(self):
        """Category detection works for known keywords."""
        from extractors.doc_parser import parse_text_dump

        text = "Devondale Full Cream Milk 2L\n$4.50\n"
        items = parse_text_dump(text, store="woolworths")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "Dairy")

    def test_detect_brand(self):
        """Brand detection works for known brands."""
        from extractors.doc_parser import parse_text_dump

        text = "Bega Tasty Cheese Block 500g\n$7.50\n"
        items = parse_text_dump(text, store="woolworths")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].brand, "Bega")

    def test_extract_size(self):
        """Size extraction works from product names."""
        from extractors.doc_parser import parse_text_dump

        text = "Oatly Barista Edition 1L\n$4.50\n"
        items = parse_text_dump(text, store="woolworths")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].size, "1L")

    def test_ignore_noise_lines(self):
        """UI noise lines are filtered out."""
        from extractors.doc_parser import parse_text_dump

        text = "toggle search\n$0.00\ntotal\n$0.00\nReal Product\n$4.50\n"
        items = parse_text_dump(text, store="woolworths")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw_name, "Real Product")


# =========================================================================
# Test Woolworths Extractor
# =========================================================================
class TestWoolworthsExtractor(unittest.TestCase):
    """Tests for the Woolworths extractor (product-detail parsing)."""

    def test_parse_product_detail(self):
        """_parse_product_detail extracts fields from a product-detail dict."""
        from extractors.woolworths_extractor import _parse_product_detail as parse

        item = parse({
            "Name": "Oatly Barista Edition 1L",
            "Price": 4.50,
            "IsAvailable": True,
            "IsOnSpecial": True,
            "WasPrice": 5.50,
            "CupPriceString": "$4.50 / 1L",
            "PackageSize": "1L",
        })
        self.assertIsNotNone(item)
        self.assertEqual(item.raw_name, "Oatly Barista Edition 1L")
        self.assertAlmostEqual(item.price, 4.50)
        self.assertTrue(item.is_special)
        self.assertIn("Was", item.special_desc)
        self.assertEqual(item.size, "1L")

    def test_parse_product_detail_no_price(self):
        """An item without a price returns 0.0."""
        from extractors.woolworths_extractor import _parse_product_detail as parse

        item = parse({"Name": "Unknown Product"})
        self.assertIsNotNone(item)
        self.assertAlmostEqual(item.price, 0.0)

    def test_parse_product_detail_empty_name(self):
        """An item without a name returns None."""
        from extractors.woolworths_extractor import _parse_product_detail as parse

        item = parse({"Price": 5.00})
        self.assertIsNone(item)

    def test_parse_product_detail_unavailable_zeroes_price(self):
        """An unavailable item keeps its name but prices as 0.0."""
        from extractors.woolworths_extractor import _parse_product_detail as parse

        item = parse({
            "DisplayName": "Woolworths Full Cream Milk 2L",
            "Price": 3.60,
            "IsAvailable": False,
        })
        self.assertIsNotNone(item)
        self.assertEqual(item.raw_name, "Woolworths Full Cream Milk 2L")
        self.assertAlmostEqual(item.price, 0.0)


# =========================================================================
# Test Coles Extractor
# =========================================================================
class TestColesExtractor(unittest.TestCase):
    """Tests for the Coles extractor (search-result parsing)."""

    def test_parse_search_result(self):
        """_parse_search_result extracts fields from a raw product dict."""
        from extractors.coles_extractor import _parse_search_result as parse

        item = parse({
            "id": "1063932",
            "name": "Coles Full Cream Milk 2L",
            "pricing": {
                "now": 3.80,
                "was": 4.50,
                "comparable": "$1.90 / 1L",
            },
            "size": "2L",
        })
        self.assertIsNotNone(item)
        self.assertEqual(item.raw_name, "Coles Full Cream Milk 2L")
        self.assertAlmostEqual(item.price, 3.80)
        self.assertTrue(item.is_special)
        self.assertEqual(item.special_desc, "Was $4.50")
        self.assertEqual(item.size, "2L")
        self.assertEqual(item.product_id, "1063932")

    def test_parse_search_result_minimal_fields(self):
        """_parse_search_result handles a flat dict with only name + price."""
        from extractors.coles_extractor import _parse_search_result as parse

        item = parse({
            "name": "Coles White Bread 700g",
            "pricing": {"now": 3.50},
        })
        self.assertIsNotNone(item)
        self.assertEqual(item.raw_name, "Coles White Bread 700g")
        self.assertAlmostEqual(item.price, 3.50)
        self.assertFalse(item.is_special)

    def test_parse_search_result_with_promotion_type(self):
        """_parse_search_result detects specials from promotionType."""
        from extractors.coles_extractor import _parse_search_result as parse

        item = parse({
            "name": "Coles Butter 250g",
            "pricing": {"now": 3.00, "promotionType": "HALF_PRICE"},
        })
        self.assertIsNotNone(item)
        self.assertTrue(item.is_special)
        self.assertEqual(item.special_desc, "Half Price")


# =========================================================================
# Test Hub
# =========================================================================
class TestHub(unittest.TestCase):
    """Tests for the extractor hub."""

    def test_get_store_products_valid_store(self):
        """get_store_products returns a list for known stores."""
        from extractors.hub import get_store_products

        for store in ("woolworths", "coles"):
            with self.subTest(store=store):
                items = get_store_products(store, force_fallback=True)
                self.assertIsInstance(items, list)

    def test_get_store_products_invalid_store(self):
        """get_store_products raises ValueError for unknown stores."""
        from extractors.hub import get_store_products

        with self.assertRaises(ValueError):
            get_store_products("unknown")

    def test_get_all_store_products(self):
        """get_all_store_products returns dict with all stores."""
        from extractors.hub import get_all_store_products

        result = get_all_store_products(force_fallback=True)
        self.assertIn("woolworths", result)
        self.assertIn("coles", result)

    def test_get_store_info(self):
        """get_store_info returns metadata for all stores."""
        from extractors.hub import get_store_info

        info = get_store_info()
        self.assertIn("woolworths", info)
        self.assertIn("coles", info)
        self.assertEqual(info["woolworths"]["label"], "Woolworths")


# =========================================================================
# Main
# =========================================================================
if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    print(f"\n{'='*60}")
    print(f"Tests run: {result.result.testsRun}")
    print(f"Failures: {len(result.result.failures)}")
    print(f"Errors: {len(result.result.errors)}")
    sys.exit(0 if result.result.wasSuccessful() else 1)
