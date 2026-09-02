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
from pathlib import Path

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

    def _docx_from_lines(self, tmpdir, lines):
        """Write a minimal .docx (one paragraph per line) for tests."""
        from docx import Document
        path = Path(tmpdir) / "list.docx"
        doc = Document()
        for ln in lines:
            doc.add_paragraph(ln)
        doc.save(str(path))
        return str(path)

    def test_multibuy_marker_under_unit_price_line_ww(self):
        """2026-09-02 Jumpy's fix: Woolworths pastes a unit-price line
        between the price and the multi-buy marker — the marker at i+3
        must still be detected (real Woolworths.docx layout)."""
        from extractors.doc_parser import parse_docx
        import tempfile

        lines = ["Jumpy's Chicken Potato Chips 5 pack",
                 "$4.00",
                 "$4.44 / 100G",
                 "2 for $7.00 - $3.89/100G"]
        with tempfile.TemporaryDirectory() as tmp:
            items = parse_docx(self._docx_from_lines(tmp, lines),
                               store="woolworths")
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "2 for $7.00")

    def test_multibuy_marker_under_unit_price_line_coles(self):
        """2026-09-02 Sunbites fix: the Coles layout with a unit-price
        at i+2 and 'Any 2 | $9' at i+3 (real Coles.docx layout)."""
        from extractors.doc_parser import parse_docx
        import tempfile

        lines = ["Sunbites Grain Waves Chips Kids' Lunchbox Multipack "
                 "8 Pack | 176g",
                 "$6.00",
                 "$3.41/ 100g",
                 "Any 2 | $9",
                 "$2.56/ 100g"]
        with tempfile.TemporaryDirectory() as tmp:
            items = parse_docx(self._docx_from_lines(tmp, lines),
                               store="coles")
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "Any 2 | $9")

    def test_unit_price_line_alone_is_not_a_special(self):
        """A plain unit-price line under the price (no marker below)
        must NOT flag a special."""
        from extractors.doc_parser import parse_docx
        import tempfile

        lines = ["Plain Oat Milk 1L", "$4.00", "$4.00 / 1L",
                 "Next Product 2L", "$3.00"]
        with tempfile.TemporaryDirectory() as tmp:
            items = parse_docx(self._docx_from_lines(tmp, lines),
                               store="woolworths")
        self.assertTrue(items)
        self.assertFalse(any(i.is_special for i in items))

    def test_multibuy_directly_below_price_still_works(self):
        """The original layout (marker at i+2, no unit-price line)
        keeps working after the skip fix."""
        from extractors.doc_parser import parse_docx
        import tempfile

        lines = ["Simple Thing 500g", "$3.00", "2 for $5.00"]
        with tempfile.TemporaryDirectory() as tmp:
            items = parse_docx(self._docx_from_lines(tmp, lines),
                               store="woolworths")
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].is_special)
        self.assertEqual(items[0].special_desc, "2 for $5.00")

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


class _FakeResponse:
    """Minimal stand-in for requests.Response (status + JSON payload)."""

    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class TestFetchWoolworthsListDiagnostics(unittest.TestCase):
    """fetch_woolworths_list must distinguish a blocked API from a
    renamed list (2026-09-01 grocery-channel incident: an Akamai 403
    from the VPS runner was mis-reported as "List not found")."""

    def setUp(self):
        import os

        self._old_cookie = os.environ.get("WOOLWORTHS_COOKIE", "")
        os.environ["WOOLWORTHS_COOKIE"] = "session=fake; token=fake"

    def tearDown(self):
        import os

        if self._old_cookie:
            os.environ["WOOLWORTHS_COOKIE"] = self._old_cookie
        else:
            os.environ.pop("WOOLWORTHS_COOKIE", None)

    def _fetch_and_capture_stderr(self, fake_responses):
        """Run fetch_woolworths_list with mocked HTTP; return stderr text."""
        import contextlib
        import io
        from unittest.mock import patch

        import extractors.woolworths_extractor as wwe

        with patch.object(
            wwe.requests, "get", side_effect=fake_responses
        ), contextlib.redirect_stderr(io.StringIO()) as err:
            items = wwe.fetch_woolworths_list("Price Compare")
        return items, err.getvalue()

    def test_blocked_api_reports_http_not_rename(self):
        """A 403 mylists response reports the block, not a rename."""
        from extractors.woolworths_extractor import _find_list_id  # noqa: F401

        blocked = [_FakeResponse(403), _FakeResponse(403)]
        items, stderr = self._fetch_and_capture_stderr(blocked)
        self.assertEqual(items, [])
        self.assertIn("Saved-list API unavailable", stderr)
        self.assertIn("HTTP 403", stderr)
        self.assertNotIn("not found", stderr)
        self.assertNotIn("Available lists", stderr)

    def test_renamed_list_reports_not_found_with_available(self):
        """A 200 response without the target name reports the rename."""
        lists_payload = {
            "Response": [
                {"Name": "Weekly Shop", "ListId": 111},
                {"Name": "BBQ", "ListId": 222},
            ]
        }
        ok = [
            _FakeResponse(200, lists_payload),
            _FakeResponse(200, lists_payload),
        ]
        items, stderr = self._fetch_and_capture_stderr(ok)
        self.assertEqual(items, [])
        self.assertIn("List 'Price Compare' not found", stderr)
        self.assertIn("Available lists", stderr)
        self.assertIn("Weekly Shop", stderr)


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
