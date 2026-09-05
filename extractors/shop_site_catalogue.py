"""Generic shop-website normal-price catalogue; Dunya today (§6.2).

WooCommerce Store API via Scrape.do (the site's TLS chain fails
direct python fetches; Scrape.do terminates TLS with a valid cert —
verification is NEVER disabled, pre-arch A5). 28-day JSON cache.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from extractors.fb_flyer_fetch import register_scrapedo_credit

STORE_SITES = [
    {"key": "dunya", "store_key": "dunya",
     "api_base": "https://www.dunyabutchery.com.au"
                 "/wp-json/wc/store/v1/products",
     "via": "scrapedo", "refresh_days": 28},
]

CATALOGUE_DIR = (Path(__file__).resolve().parent.parent
                 / "data" / "shop_catalogues")
PAGE_SIZE = 50
REQUEST_TIMEOUT_S = 60.0


def get_catalogue(store_key: str, force: bool = False) -> dict | None:
    """Load (and refresh when stale) a shop's site catalogue.

    Cache file data/shop_catalogues/<store_key>.json holds
    {"fetched_at": ISO, "products": [...]}. Stale = older than the
    registry's refresh_days. force always refreshes. Returns None
    when no cache exists AND the fetch fails (site prices absent;
    comments degrade gracefully).
    """
    site = next((s for s in STORE_SITES if s["key"] == store_key), None)
    if site is None:
        return None
    CATALOGUE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CATALOGUE_DIR / f"{store_key}.json"
    data = _load_cache(cache)
    stale = (data is None or _age_days(data) >= site["refresh_days"])
    if stale or force:
        _refresh(site, cache)
        data = _load_cache(cache)  # refresh wrote it (or not)
    return data


def get_normalised_catalogue(store_key: str,
                             force: bool = False) -> list[dict]:
    """[_normalise(p) for p in products] — [] when no catalogue."""
    data = get_catalogue(store_key, force=force)
    if not data:
        return []
    return [_normalise(p) for p in data.get("products", [])]


def _age_days(data: dict) -> float:
    """Cache age in days; 1e9 (always stale) on corrupt/missing ts."""
    try:
        fetched = datetime.fromisoformat(data["fetched_at"])
        return (datetime.now(timezone.utc) - fetched).total_seconds() / 86400
    except (KeyError, ValueError):
        return 1e9


def _load_cache(cache: Path) -> dict | None:
    """Parse the cache file; None on missing/corrupt (graceful)."""
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _refresh(site: dict, cache: Path) -> bool:
    """Fetch all pages via Scrape.do; write the cache. False on fail."""
    try:
        products = _fetch_via_scrapedo(site["api_base"])
    except (requests.RequestException, RuntimeError, ValueError):
        print(f"[shop_site_catalogue] refresh failed for "
              f"{site['key']} — keeping stale cache", flush=True)
        return False
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(
        timespec="seconds"), "products": products}
    cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True


def _fetch_via_scrapedo(api_base: str) -> list[dict]:
    """Paginated walk ?per_page=50&page=N until a short/empty page.

    MANDATORY: routed through Scrape.do (TLS chain; verification
    never disabled). Each page registers one credit.
    """
    out: list[dict] = []
    page = 1
    while True:
        if not register_scrapedo_credit():
            break
        params = {
            "token": os.getenv("SCRAPEDO_API_KEY", ""),
            "url": f"{api_base}?per_page={PAGE_SIZE}&page={page}",
            "geoCode": "au",
        }
        resp = requests.get("https://api.scrape.do", params=params,
                            timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        items = resp.json() or []
        out.extend(items)
        if len(items) < PAGE_SIZE:
            return out
        page += 1


def _normalise(product_json: dict) -> dict:
    """{name, price, regular_price, categories, unit} from WC item.

    unit parsed from the product name ("(per kg)" -> "kg",
    "(each)" -> "ea", else "").
    """
    name = str(product_json.get("name") or "").strip()
    low = name.lower()
    unit = ""
    if "(per kg)" in low or "per kg" in low:
        unit = "kg"
    elif "(each)" in low or "per each" in low:
        unit = "ea"

    def _num(v):
        """float when the WC price parses, else None."""
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    prices = product_json.get("prices") or {}
    return {
        "name": name,
        "price": _num(prices.get("price")),
        "regular_price": _num(prices.get("regular_price")),
        "categories": [str(c.get("name") or "")
                       for c in product_json.get("categories") or []],
        "unit": unit,
    }
