"""Generic shop-website normal-price catalogue; Dunya today (§6.2),
Nazar since 2026-09-12.

WooCommerce Store API. Dunya's TLS chain fails direct python fetches
— routed through Scrape.do (verification NEVER disabled, pre-arch
A5). Nazar answers a DIRECT fetch (verified 2026-09-12), so it is
fetched directly with a Scrape.do fallback in case that ever
changes. 28-day JSON cache.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from extractors.fb_flyer_fetch import register_scrapedo_credit

STORE_SITES = [
    {"key": "dunya", "store_key": "dunya",
     "api_base": "https://www.dunyabutchery.com.au"
                 "/wp-json/wc/store/v1/products",
     "via": "scrapedo", "refresh_days": 28},
    {"key": "nazar", "store_key": "nazar",
     "api_base": "https://nazarbutchery.com.au"
                 "/wp-json/wc/store/v1/products",
     "via": "direct", "refresh_days": 28},
]

CATALOGUE_DIR = (Path(__file__).resolve().parent.parent
                 / "data" / "shop_catalogues")
PAGE_SIZE = 50
REQUEST_TIMEOUT_S = 60.0

# Nazar carries the sales unit IN the price display ('$16.90 per
# kg', '$7.50 per item', '$5.00 per 100g') — the name carries none.
_DISPLAY_UNIT_RE = re.compile(
    r"per\s+(kg|100g|pack|item|each)\s*$", re.IGNORECASE)
# A per-100g price × 10 IS the per-kg rate (deli items).
_PER100G_SCALE = 10.0


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
    """Fetch all pages via the site's route; write the cache. False
    on fail.

    An EMPTY fetch (0 products — transient site/Scrape.do hiccup)
    is treated as a failure: the previous good cache is kept instead
    of being overwritten with nothing (2026-09-06).
    """
    try:
        products = _fetch_products(site)
    except (requests.RequestException, RuntimeError, ValueError):
        print(f"[shop_site_catalogue] refresh failed for "
              f"{site['key']} — keeping stale cache", flush=True)
        return False
    if not products:
        print(f"[shop_site_catalogue] refresh returned 0 products "
              f"for {site['key']} — keeping stale cache", flush=True)
        return False
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(
        timespec="seconds"), "products": products}
    cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True


def _fetch_products(site: dict) -> list[dict]:
    """Walk the catalogue by the site's registered route.

    'direct': plain requests (Nazar — TLS chain verified 2026-09-12);
    on ANY failure the Scrape.do route is tried once, so a site that
    starts blocking python TLS degrades gracefully instead of
    breaking the sync.
    'scrapedo': Scrape.do only (Dunya — direct fetches never worked).
    """
    if site.get("via") == "direct":
        try:
            return _fetch_paginated(site["api_base"])
        except requests.RequestException as exc:
            print(f"[shop_site_catalogue] {site['key']}: direct "
                  f"fetch failed ({exc.__class__.__name__}) — "
                  f"falling back to Scrape.do", flush=True)
    return _fetch_via_scrapedo(site["api_base"])


def _fetch_paginated(api_base: str) -> list[dict]:
    """Paginated walk ?per_page=50&page=N until a short/empty page."""
    out: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            api_base,
            params={"per_page": PAGE_SIZE, "page": page},
            timeout=REQUEST_TIMEOUT_S,
            headers={"User-Agent": "Mozilla/5.0 (grocery-price-tracker)"},
        )
        resp.raise_for_status()
        items = resp.json() or []
        out.extend(items)
        if len(items) < PAGE_SIZE:
            return out
        page += 1


def _fetch_via_scrapedo(api_base: str) -> list[dict]:
    """Paginated walk via Scrape.do (TLS terminated there; cert
    verification never disabled). Each page registers one credit."""
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


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ",
                  re.sub(r"<[^>]+>", " ", html or "")).strip()


def _display_unit(price_html: str) -> str:
    """Sales unit from the price display ('per kg', 'per item',
    'per pack', 'per 100g'), '' when the display states none."""
    m = _DISPLAY_UNIT_RE.search(_strip_tags(price_html))
    return m.group(1).lower() if m else ""


def _price_range_text(price_html: str) -> str:
    """'12.90-14.90' when the display is a range ('$12.90 – $14.90
    per item' — weight-priced variable products), else ''."""
    text = _strip_tags(price_html)
    m = re.search(r"\$(\d+(?:\.\d+)?)\s*[-\u2013]\s*\$(\d+(?:\.\d+)?)",
                  text)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def _normalise(product_json: dict) -> dict:
    """{name, price, regular_price, categories, unit, display_unit,
    price_range} from a WC item.

    unit parsed from the product NAME ("(per kg)" -> "kg",
    "(each)" -> "ea", else "") — the Dunya convention. display_unit
    parsed from the price DISPLAY ('per kg' ...) — the Nazar
    convention (names carry no unit there). price_range keeps a
    weight-priced range ('$12.90 – $14.90') for the sync's notes.
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
        "display_unit": _display_unit(
            str(product_json.get("price_html") or "")),
        "price_range": _price_range_text(
            str(product_json.get("price_html") or "")),
    }
