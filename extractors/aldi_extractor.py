#!/usr/bin/env python3
"""Aldi AU extractor: public JSON API via curl_cffi Chrome-131.

All Aldi HTTP lives here (live search + special buys). PRICES ONLY —
this module never imports sheets, telegram, or CLI code and never
writes anything (spec §3.1, verdict V1).
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup (mirrors woolworths_extractor) so the __main__ self-test
# runs via `python extractors/aldi_extractor.py` from any cwd.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_TRACKER_DIR = os.path.abspath(os.path.join(_HERE, ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
for _p in (_TRACKER_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from extractors.models import ProductItem

ALDI_API_BASE = "https://api.aldi.com.au"
ALDI_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.aldi.com.au",
    "Referer": "https://www.aldi.com.au/",
}
# Fixed param contract (pre-arch gotchas): limit MUST be 30 (the API
# 400s other values); servicePoint G406 = Mt Druitt area store (the
# site's own geolocated choice; omitting it drops the odd product).
ALDI_FIXED_PARAMS = {"serviceType": "walk-in", "limit": 30,
                     "sort": "relevance", "servicePoint": "G406"}
ALDI_TIMEOUT_S = 20
ALDI_RETRIES = 2          # 1 try + 1 retry after 2 s
ALDI_RETRY_PAUSE_S = 2.0


class AldiAPIError(RuntimeError):
    """Transport/HTTP failure after retries (spec §4.5 V9 path)."""


def _request(path: str, params: dict):
    """ONE curl_cffi chrome131 GET. Raises on transport failure.
    Patch point for tests (never import curl_cffi elsewhere)."""
    from curl_cffi import requests as cffi_requests
    return cffi_requests.get(f"{ALDI_API_BASE}{path}", params=params,
                             impersonate="chrome131",
                             headers=ALDI_HEADERS, timeout=ALDI_TIMEOUT_S)


def _aldi_get(path: str, extra_params: Optional[dict] = None) -> dict:
    """GET one Aldi API endpoint -> parsed JSON dict.

    Retries once after 2 s on non-200/network error, then raises
    AldiAPIError. Never returns partial data.
    """
    params = dict(ALDI_FIXED_PARAMS)
    if extra_params:
        params.update(extra_params)
    last: Exception = AldiAPIError("unreachable")
    for attempt in range(ALDI_RETRIES):
        try:
            resp = _request(path, params)
            if resp.status_code == 200:
                return resp.json()
            last = AldiAPIError(f"HTTP {resp.status_code}")
        except AldiAPIError:
            last = sys.exc_info()[1]
        except Exception as exc:            # noqa: BLE001 — transport
            last = exc
        if attempt < ALDI_RETRIES - 1:
            time.sleep(ALDI_RETRY_PAUSE_S)
    raise AldiAPIError(f"{path}: {last}")


def _to_product_item(p: dict) -> Optional[ProductItem]:
    """One Aldi product dict -> ProductItem (None when unusable).

    price.amount is CENTS. Items without a usable price are dropped
    (mirrors the WW noauth guard); notForSale items are KEPT (real
    prices). Specials flags come from wasPrice/savings displays.
    """
    name = str(p.get("name") or "").strip()
    price_block = p.get("price") or {}
    amount = price_block.get("amount")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0
    if not name or amount <= 0:
        return None
    was = price_block.get("wasPriceDisplay") or ""
    sav = price_block.get("savingsDisplay") or ""
    item = ProductItem(
        store="aldi",
        raw_name=name,
        price=round(amount / 100.0, 2),
        is_special=bool(was or sav),
        special_desc=str(sav or was or ""),
        unit_price=str(price_block.get("comparisonDisplay") or ""),
        brand=str(p.get("brandName") or ""),
        size=str(p.get("sellingSize") or ""),
        product_id=str(p.get("sku") or ""),
    )
    item._theme_categories = [
        str(c.get("name") or "").strip()
        for c in (p.get("categories") or [])
        if isinstance(c, dict) and c.get("name")
    ]
    assets = p.get("assets") or []
    item._hero_asset = str(assets[0].get("url") or "") \
        if assets and isinstance(assets[0], dict) else ""
    return item


def fetch_aldi_search(search_term: str, page_size: int = 10
                      ) -> list[ProductItem]:
    """Live search (spec §3.1): q=<term> on /v3/product-search."""
    data = _aldi_get("/v3/product-search", {"q": search_term})
    items: list[ProductItem] = []
    for p in (data.get("data") or [])[:max(1, page_size)]:
        item = _to_product_item(p)
        if item is not None:
            items.append(item)
    return items


def fetch_promotion_tree() -> list[dict]:
    """Upcoming Special Buys drops, each keyed by ISO date
    (pre-arch §5.1). Returns data.promotions (possibly [])."""
    data = _aldi_get("/v2/promotion-tree")
    return ((data.get("data") or {}).get("promotions")) or []


def find_promotion(date_iso: str) -> Optional[dict]:
    """The promotion whose key EQUALS date_iso (never 'newest' —
    drops are visible ~2 weeks early; spec §4.2 / verdict V3)."""
    for promo in fetch_promotion_tree():
        if str(promo.get("key") or "") == date_iso:
            return promo
    return None


def fetch_aldi_specials(date_iso: str) -> list[ProductItem]:
    """One day's Special Buys via promotionKey=<date>, paginated
    30/page until a short page (spec §4.2; 94 items ≈ 4 pages)."""
    items: list[ProductItem] = []
    offset = 0
    while True:
        page = _aldi_get("/v3/product-search",
                         {"promotionKey": date_iso, "offset": offset})
        rows = page.get("data") or []
        for p in rows:
            item = _to_product_item(p)
            if item is not None:
                items.append(item)
        if len(rows) < ALDI_FIXED_PARAMS["limit"]:
            break
        offset += ALDI_FIXED_PARAMS["limit"]
    return items


if __name__ == "__main__":
    _found = fetch_aldi_search("milk")
    print(f"search 'milk': {len(_found)} items")
    _promos = fetch_promotion_tree()
    print(f"promotion keys: {[p.get('key') for p in _promos]}")
    if _promos:
        _latest = str(_promos[-1].get("key") or "")
        _specials = fetch_aldi_specials(_latest)
        print(f"specials {_latest}: {len(_specials)} items")
