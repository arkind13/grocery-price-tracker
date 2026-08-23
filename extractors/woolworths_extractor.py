#!/usr/bin/env python3
"""Woolworths list extractor: fetch saved-list products via authenticated API.

Requires ``WOOLWORTHS_COOKIE`` in root ``.env`` (session cookie from logged-in
browser session).

API endpoints (verified working 2026-08-22):
  - ``/apis/ui/mylists`` -- list all saved lists
  - ``/apis/ui/mylists/{id}`` -- get list items (ArticleIds)
  - ``/apis/ui/product/detail/{ArticleId}`` -- full product details
  - ``/apis/ui/Search/products`` -- keyword search

Usage:
    from extractors.woolworths_extractor import fetch_woolworths_list
    items = fetch_woolworths_list()
    for item in items:
        print(item.raw_name, item.price, item.is_special)
"""

import json
import os
import sys
import time
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
from extractors.session_manager import SessionManager

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MYLISTS_API = "https://www.woolworths.com.au/apis/ui/mylists"
MYLIST_API = "https://www.woolworths.com.au/apis/ui/mylists/{list_id}"
PRODUCT_DETAIL_API = "https://www.woolworths.com.au/apis/ui/product/detail/{article_id}"
SEARCH_API = "https://www.woolworths.com.au/apis/ui/Search/products"

DEFAULT_TIMEOUT = 30
LIST_NAME_TARGET = "Price Compare"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_env():
    if not load_dotenv:
        return
    env_path = os.path.join(_REPO_ROOT, ".env")
    if os.path.isfile(env_path):
        load_dotenv(env_path)


_load_env()


# ---------------------------------------------------------------------------
# Cookie-based headers
# ---------------------------------------------------------------------------
def _build_headers(session: Optional[SessionManager] = None) -> dict:
    """Build HTTP headers with session cookie.

    Args:
        session: Optional SessionManager to inject cookie.

    Returns:
        dict of HTTP headers.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.woolworths.com.au/shop/mylists",
        "Origin": "https://www.woolworths.com.au",
    }
    if session and session.has_cookie("woolworths"):
        headers["Cookie"] = session.get_cookie_string("woolworths")
    return headers


# ---------------------------------------------------------------------------
# Step 1: Find list ID by name
# ---------------------------------------------------------------------------
def _find_list_id(list_name: str, session: SessionManager) -> Optional[int]:
    """Find a saved list ID by its name.

    Args:
        list_name: Name of the saved list (e.g. ``"Price Compare"``).
        session: SessionManager with valid cookie.

    Returns:
        List ID (int), or None if not found.
    """
    headers = _build_headers(session)
    try:
        resp = requests.get(MYLISTS_API, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code != 200:
            return None

        data = resp.json()
        lists = data.get("Response", [])
        for lst in lists:
            if lst.get("Name", "").strip().lower() == list_name.strip().lower():
                return lst.get("ListId")
        return None
    except (requests.RequestException, json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Step 2: Get list items (ArticleIds with quantities)
# ---------------------------------------------------------------------------
def _get_list_items(list_id: int, session: SessionManager) -> list[dict]:
    """Get items from a saved list.

    Args:
        list_id: ID of the saved list.
        session: SessionManager with valid cookie.

    Returns:
        List of dicts with ``ArticleId`` and ``Quantity``.
    """
    headers = _build_headers(session)
    try:
        resp = requests.get(
            MYLIST_API.format(list_id=list_id),
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("Products", [])
    except (requests.RequestException, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# Step 3: Fetch product details for a single ArticleId
# ---------------------------------------------------------------------------
def _get_product_detail(article_id: int, headers: dict) -> Optional[dict]:
    """Fetch full product details from Woolworths API.

    Args:
        article_id: Woolworths ArticleId (Stockcode).
        headers: HTTP headers with session cookie.

    Returns:
        Product dict (the ``Product`` field from the response), or None.
    """
    try:
        resp = requests.get(
            PRODUCT_DETAIL_API.format(article_id=article_id),
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("Product")
    except (requests.RequestException, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# Step 4: Parse product detail into ProductItem
# ---------------------------------------------------------------------------
def _parse_product_detail(product: dict, quantity: float = 1.0) -> Optional[ProductItem]:
    """Parse a Woolworths product detail dict into a ``ProductItem``.

    Args:
        product: The ``Product`` field from the product detail API response.
        quantity: Quantity of this item in the saved list.

    Returns:
        ``ProductItem`` or None if parsing fails.
    """
    if not product:
        return None

    # Name
    raw_name = product.get("DisplayName") or product.get("Name", "")
    if not raw_name:
        return None

    # Price
    price = product.get("Price", 0.0)
    try:
        price = float(price) if price else 0.0
    except (ValueError, TypeError):
        price = 0.0

    # Specials
    is_special = bool(product.get("IsOnSpecial", False))
    is_half_price = bool(product.get("IsHalfPrice", False))
    was_price = product.get("WasPrice", 0.0)
    savings = product.get("SavingsAmount", 0.0)

    special_desc = ""
    if is_special and was_price and float(was_price) > 0:
        special_desc = f"Was ${float(was_price):.2f}"
    elif is_half_price:
        special_desc = "Half Price"
    elif is_special and float(savings) > 0:
        special_desc = f"Save ${float(savings):.2f}"

    # Unit price (e.g. "$2.35 / 1L")
    unit_price = product.get("CupString", product.get("CupPriceString", ""))

    # Brand
    brand = product.get("Brand", "")

    # Size
    size = product.get("PackageSize", "")

    # Rewards points (not directly in product detail)
    rewards_points = ""

    # Product is available
    is_available = product.get("IsAvailable", False)

    return ProductItem(
        store="woolworths",
        raw_name=raw_name,
        price=price if is_available else 0.0,
        is_special=is_special,
        special_desc=special_desc,
        rewards_points=rewards_points,
        unit_price=str(unit_price) if unit_price else "",
        brand=str(brand) if brand else "",
        size=str(size) if size else "",
    )


# ---------------------------------------------------------------------------
# Public API: fetch full list
# ---------------------------------------------------------------------------
def fetch_woolworths_list(
    list_name: str = LIST_NAME_TARGET,
    force_fallback: bool = False,
) -> list[ProductItem]:
    """Fetch product items from a Woolworths saved list.

    Requires ``WOOLWORTHS_COOKIE`` in root ``.env``.

    Args:
        list_name: Name of the saved list (default: ``"Price Compare"``).
        force_fallback: If True, skip API and use offline fallback.

    Returns:
        list of ``ProductItem`` instances. Empty if unavailable.

    Raises:
        No exceptions raised; failures logged to stderr.
    """
    session = SessionManager()

    if not force_fallback:
        if not session.has_cookie("woolworths"):
            print(
                "[woolworths_extractor] WOOLWORTHS_COOKIE not set in .env",
                file=sys.stderr,
            )
            return []

        # Step 1: Find list ID
        list_id = _find_list_id(list_name, session)
        if not list_id:
            print(
                f"[woolworths_extractor] List '{list_name}' not found",
                file=sys.stderr,
            )
            # Try listing all available lists
            headers = _build_headers(session)
            try:
                resp = requests.get(MYLISTS_API, headers=headers, timeout=DEFAULT_TIMEOUT)
                if resp.status_code == 200:
                    all_lists = resp.json().get("Response", [])
                    names = [lst.get("Name", "?") for lst in all_lists]
                    print(
                        f"  Available lists: {names}",
                        file=sys.stderr,
                    )
            except Exception:
                pass
            return []

        # Step 2: Get list items
        list_items = _get_list_items(list_id, session)
        if not list_items:
            print(
                f"[woolworths_extractor] No items found in list '{list_name}'",
                file=sys.stderr,
            )
            return []

        print(
            f"[woolworths_extractor] Found {len(list_items)} items in "
            f"'{list_name}', fetching details...",
            file=sys.stderr,
        )

        # Step 3: Fetch product details for each item
        headers = _build_headers(session)
        products = []
        total = len(list_items)

        for i, item in enumerate(list_items):
            article_id = item.get("ArticleId")
            quantity = item.get("Quantity", 1.0)

            if not article_id:
                continue

            product_detail = _get_product_detail(article_id, headers)
            parsed = _parse_product_detail(product_detail, quantity)

            if parsed:
                products.append(parsed)

            # Progress indicator
            if (i + 1) % 20 == 0:
                print(
                    f"  ... {i + 1}/{total} products fetched",
                    file=sys.stderr,
                )
                time.sleep(0.3)

        print(
            f"[woolworths_extractor] Fetched {len(products)} products with "
            f"prices from '{list_name}'",
            file=sys.stderr,
        )
        return products

    # Fallback: try offline payload
    html = session.load_fallback_payload("woolworths")
    if html:
        from extractors.doc_parser import parse_text_dump
        # Try simple text parsing as fallback
        print("[woolworths_extractor] Fallback payload loaded", file=sys.stderr)

    return []


# ---------------------------------------------------------------------------
# Public API: search products
# ---------------------------------------------------------------------------
def fetch_woolworths_search(
    search_term: str, page_size: int = 10
) -> list[ProductItem]:
    """Search Woolworths products by keyword.

    Uses the search API with the session cookie for authentication.

    Args:
        search_term: Keyword to search for.
        page_size: Number of results (max 48).

    Returns:
        list of ``ProductItem`` instances.
    """
    session = SessionManager()
    headers = _build_headers(session)
    headers["Content-Type"] = "application/json"

    payload = {
        "SearchTerm": search_term,
        "PageNumber": 1,
        "PageSize": min(page_size, 48),
        "SortType": "TraderRelevance",
    }

    try:
        resp = requests.post(
            SEARCH_API, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        if resp.status_code != 200:
            return []

        data = resp.json()
        raw_products = data.get("Products", [])

        products = []
        seen = set()
        for item in raw_products:
            # Search results have a nested structure with 'Products' key
            actual_product = item.get("Products", [{}])[0] if isinstance(item.get("Products"), list) else item
            name = actual_product.get("DisplayName") or actual_product.get("Name", "")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())

            price = actual_product.get("Price", 0.0)
            try:
                price = float(price) if price else 0.0
            except (ValueError, TypeError):
                price = 0.0

            is_special = bool(actual_product.get("IsOnSpecial", False))
            was_price = actual_product.get("WasPrice", 0.0)

            special_desc = ""
            if is_special and float(was_price) > 0:
                special_desc = f"Was ${float(was_price):.2f}"

            products.append(
                ProductItem(
                    store="woolworths",
                    raw_name=name,
                    price=price,
                    is_special=is_special,
                    special_desc=special_desc,
                    unit_price=str(actual_product.get("CupString", "")),
                    brand=str(actual_product.get("Brand", "")),
                    size=str(actual_product.get("PackageSize", "")),
                )
            )
        return products
    except (requests.RequestException, json.JSONDecodeError) as exc:
        print(f"[woolworths_extractor] Search failed: {exc}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Public API: browse specials (site-wide deep discounts)
# ---------------------------------------------------------------------------

def fetch_woolworths_specials_browse(
    min_savings_pct: int = 50,
    page_size: int = 48,
) -> list[ProductItem]:
    """Best-effort fetch of site-wide Woolworths specials (deep discounts).

    Probes the Woolworths browse/specials category endpoint. If the endpoint
    is blocked (403) or returns no specials, returns [] (caller degrades to
    saved-list scan). Never raises.

    Args:
        min_savings_pct: minimum savings percentage filter (0-100).
        page_size: max products to return.

    Returns:
        list[ProductItem] (empty on failure).
    """
    import requests

    cookie = os.getenv("WOOLWORTHS_COOKIE", "")
    if not cookie:
        return []

    session = requests.Session()
    headers = _build_headers(session)
    headers.setdefault("Cookie", cookie)

    # Primary endpoint candidate: browse specials category
    url = "https://www.woolworths.com.au/apis/ui/browse/specials"

    try:
        resp = session.get(url, headers=headers, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except Exception:
        return []

    items = []
    try:
        # Probe known response shapes
        products = (
            data.get("SeoMetaTags", {}).get("Products")
            or data.get("Bundles")
            or data.get("Products")
            or []
        )
        for raw in products[:page_size]:
            parsed = _parse_product_detail(raw)
            if parsed is not None and parsed.price is not None:
                items.append(parsed)
    except Exception:
        pass

    return items


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Woolworths Extractor Self-Test ===\n")

    # Test 1: Fetch the saved list
    print("1. Fetching 'Price Compare' list...")
    items = fetch_woolworths_list("Price Compare")
    print(f"   Found {len(items)} items\n")

    if items:
        print("   --- First 10 items ---")
        for item in items[:10]:
            special = f" [SPECIAL: {item.special_desc}]" if item.is_special else ""
            print(f"   - {item.raw_name}: ${item.price:.2f}{special}")

        # Stats
        with_prices = sum(1 for i in items if i.price > 0)
        on_special = sum(1 for i in items if i.is_special)
        print(f"\n   Summary: {len(items)} total, {with_prices} with prices, "
              f"{on_special} on special")

    # Test 2: Search
    print("\n2. Searching for 'milk'...")
    results = fetch_woolworths_search("milk", page_size=3)
    for r in results[:3]:
        print(f"   - {r.raw_name}: ${r.price:.2f}")

    print("\n=== Done ===")
