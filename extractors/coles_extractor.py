#!/usr/bin/env python3
"""Coles product extractor: search products via Scrape.do + list via docx fallback.

Coles uses Incapsula WAF that blocks all automated POST requests (including
GraphQL). However, Scrape.do with JS render can bypass Incapsula for GET
requests. This module uses Scrape.do to render the search results page and
extract product data from the embedded ``__NEXT_DATA__`` JSON.

Shopping list extraction is not available via live API due to Incapsula;
falls back to ``Coles.docx`` parsing.

Usage:
    from extractors.coles_extractor import fetch_coles_search
    items = fetch_coles_search("milk")
    for item in items:
        print(item.raw_name, item.price, item.is_special)
"""

import json
import os
import re
import sys
from typing import Optional

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_TRACKER_DIR = os.path.abspath(os.path.join(_HERE, ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
for p in (_TRACKER_DIR, _REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from extractors.models import ProductItem
from extractors.doc_parser import parse_docx_cache

# ---------------------------------------------------------------------------
# Env / config
# ---------------------------------------------------------------------------
def _load_env():
    if not load_dotenv:
        return
    env_path = os.path.join(_REPO_ROOT, ".env")
    if os.path.isfile(env_path):
        load_dotenv(env_path)

_load_env()

SCRAPEDO_API_KEY = os.getenv("SCRAPEDO_API_KEY", "")
COLES_API_KEY = os.getenv("COLES_API_KEY", "eae83861d1cd4de6bb9cd8a2cd6f041e")

DEFAULT_TIMEOUT = 60  # Scrape.do can be slow with JS render


# ---------------------------------------------------------------------------
# Scrape.do search
# ---------------------------------------------------------------------------
def _search_via_scrapedo(search_term: str, page_size: int = 10) -> Optional[list[dict]]:
    """Search Coles products via Scrape.do with JS render.

    Fetches the search results page through Scrape.do (which bypasses
    Incapsula) and extracts product data from the embedded
    ``__NEXT_DATA__`` JSON.

    Args:
        search_term: Product keyword to search for.
        page_size: Max results to return.

    Returns:
        List of raw product dicts, or None on failure.
    """
    if not SCRAPEDO_API_KEY:
        print("[coles_extractor] SCRAPEDO_API_KEY not set in .env", file=sys.stderr)
        return None

    search_url = (
        f"https://www.coles.com.au/search?q={requests.utils.quote(search_term)}"
    )

    params = {
        "token": SCRAPEDO_API_KEY,
        "url": search_url,
        "render": "true",
        "super": "true",
        "country": "au",
        "session": "coles_extractor",
        "wait": "5000",
    }

    try:
        resp = requests.get(
            "https://api.scrape.do",
            params=params,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            print(
                f"[coles_extractor] Scrape.do returned HTTP {resp.status_code}",
                file=sys.stderr,
            )
            return None

        html = resp.text

        # Extract __NEXT_DATA__ from HTML
        next_match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not next_match:
            print("[coles_extractor] No __NEXT_DATA__ found in page", file=sys.stderr)
            return None

        next_data = json.loads(next_match.group(1))
        search_results = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("searchResults", {})
        )
        results = search_results.get("results", [])

        if not results:
            print("[coles_extractor] No search results found", file=sys.stderr)
            return None

        return results[:page_size]

    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        print(f"[coles_extractor] Search failed: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Parse search result into ProductItem
# ---------------------------------------------------------------------------
def _parse_search_result(item: dict) -> Optional[ProductItem]:
    """Parse a single Coles search result into a ProductItem.

    Args:
        item: Raw product dict from the search results.

    Returns:
        ProductItem or None.
    """
    name = item.get("name", "")
    if not name:
        return None

    brand = item.get("brand", "")
    size = item.get("size", "")
    description = item.get("description", "")

    # Pricing
    pricing = item.get("pricing", {})
    price = pricing.get("now", 0) if isinstance(pricing, dict) else 0
    was_price = pricing.get("was", 0) if isinstance(pricing, dict) else 0
    unit_price = pricing.get("comparable", "") if isinstance(pricing, dict) else ""
    online_special = pricing.get("onlineSpecial", False) if isinstance(pricing, dict) else False
    promotion_type = pricing.get("promotionType", "") if isinstance(pricing, dict) else ""

    try:
        price = float(price) if price else 0.0
    except (ValueError, TypeError):
        price = 0.0

    try:
        was_price = float(was_price) if was_price else 0.0
    except (ValueError, TypeError):
        was_price = 0.0

    # Detect specials
    is_special = online_special or (was_price > 0 and was_price > price)
    special_desc = ""
    if is_special and was_price > 0:
        special_desc = f"Was ${was_price:.2f}"
    elif promotion_type and promotion_type != "NOT_SET":
        is_special = True
        special_desc = promotion_type.replace("_", " ").title()

    # Use description as fallback name if it's more descriptive
    display_name = name
    if description and description != name:
        display_name = description

    return ProductItem(
        store="coles",
        raw_name=display_name,
        price=price,
        is_special=is_special,
        special_desc=special_desc,
        unit_price=str(unit_price) if unit_price else "",
        brand=str(brand) if brand else "",
        size=str(size) if size else "",
    )


# ---------------------------------------------------------------------------
# Public API: search
# ---------------------------------------------------------------------------
def fetch_coles_search(
    search_term: str, page_size: int = 10
) -> list[ProductItem]:
    """Search Coles products by keyword.

    Uses Scrape.do to bypass Incapsula WAF. Returns products with
    current prices, specials, and unit pricing.

    Args:
        search_term: Keyword to search for (e.g. ``"milk"``, ``"beef lasagne"``).
        page_size: Number of results to return (max 48).

    Returns:
        list of ``ProductItem`` instances. Empty if search fails.
    """
    results = _search_via_scrapedo(search_term, page_size=page_size)
    if not results:
        return []

    products = []
    seen = set()
    for item in results:
        # Skip non-product entries (ads, banners, etc.)
        if item.get("_type") != "PRODUCT":
            continue

        parsed = _parse_search_result(item)
        if parsed:
            # Deduplicate by name
            name_lower = parsed.raw_name.lower()
            if name_lower not in seen:
                seen.add(name_lower)
                products.append(parsed)

    print(
        f"[coles_extractor] Search '{search_term}': found {len(products)} products",
        file=sys.stderr,
    )
    return products


# ---------------------------------------------------------------------------
# Public API: list fetch (docx fallback)
# ---------------------------------------------------------------------------
def fetch_coles_list(
    list_name: str = "Price Comparison",
    force_fallback: bool = False,
) -> list[ProductItem]:
    """Fetch products from a Coles saved list.

    Coles list extraction via live API is blocked by Incapsula WAF.
    Falls back to parsing ``Coles.docx`` from the project directory.

    Args:
        list_name: Ignored (lists are read from docx).
        force_fallback: If True, only use docx fallback.

    Returns:
        list of ``ProductItem`` instances.
    """
    items = parse_docx_cache("coles")
    if items:
        print(
            f"[coles_extractor] Docx fallback: parsed {len(items)} items",
            file=sys.stderr,
        )
        return items

    print("[coles_extractor] No data source available for Coles list", file=sys.stderr)
    return []


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Coles Extractor Self-Test ===\n")

    # Test 1: Search
    print("1. Searching for 'milk'...")
    items = fetch_coles_search("milk", page_size=5)
    for item in items[:5]:
        special = f" [SPECIAL: {item.special_desc}]" if item.is_special else ""
        print(f"   - {item.raw_name}: ${item.price:.2f}{special}")

    # Test 2: Generic search
    print("\n2. Searching for 'beef lasagne'...")
    items = fetch_coles_search("beef lasagne", page_size=5)
    for item in items[:5]:
        special = f" [SPECIAL: {item.special_desc}]" if item.is_special else ""
        print(f"   - {item.raw_name}: ${item.price:.2f}{special}")

    # Test 3: Docx list
    print("\n3. Fetching Coles list (docx)...")
    items = fetch_coles_list()
    print(f"   Found {len(items)} items")

    print("\n=== Done ===")
