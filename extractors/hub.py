#!/usr/bin/env python3
"""Unified extractor hub: single entrypoint for all supermarket extractors.

Provides ``get_store_products(store_name)`` returning a list of
standardised ``ProductItem`` dataclasses. Combines Woolworths, Coles,
and Aldi extractors under one interface.

Usage:
    from extractors.hub import get_store_products, ProductItem

    # Fetch from all stores
    for store in ("woolworths", "coles", "aldi"):
        items = get_store_products(store)
        print(f"{store}: {len(items)} products")
"""

import sys
from typing import Optional

from extractors.models import ProductItem
from extractors.woolworths_extractor import fetch_woolworths_list
from extractors.coles_extractor import fetch_coles_list

# ---------------------------------------------------------------------------
# Aldi: no dedicated extractor yet, uses doc parser fallback
# ---------------------------------------------------------------------------
try:
    from extractors.doc_parser import parse_docx_cache
except ImportError:
    parse_docx_cache = None

# ---------------------------------------------------------------------------
# Store registry
# ---------------------------------------------------------------------------
STORE_REGISTRY = {
    "woolworths": {
        "label": "Woolworths",
        "fetcher": lambda **kw: fetch_woolworths_list(**kw),
        "supports_live_api": True,
        "supports_docx": True,
    },
    "coles": {
        "label": "Coles",
        "fetcher": lambda **kw: fetch_coles_list(**kw),
        "supports_live_api": True,
        "supports_docx": True,
    },
    "aldi": {
        "label": "Aldi",
        "fetcher": None,  # No dedicated extractor yet
        "supports_live_api": False,
        "supports_docx": True,
    },
}

ALL_STORES = tuple(STORE_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_store_products(
    store: str,
    list_name: str = "Price Comparison",
    force_fallback: bool = False,
) -> list[ProductItem]:
    """Fetch product items from a single supermarket.

    Args:
        store: Store identifier. One of: ``"woolworths"``, ``"coles"``,
            ``"aldi"``.
        list_name: Name of the saved list (default: ``"Price Comparison"``).
            Only used by Woolworths and Coles extractors.
        force_fallback: If True, skip live API and scraping API, use
            only offline/fallback sources.

    Returns:
        list of ``ProductItem`` instances. Empty if store not recognised
        or all data sources fail.

    Raises:
        ValueError: If ``store`` is not a recognised identifier.
    """
    store = store.lower().strip()
    config = STORE_REGISTRY.get(store)
    if not config:
        raise ValueError(
            f"Unknown store '{store}'. "
            f"Supported: {', '.join(ALL_STORES)}"
        )

    # Use dedicated fetcher if available
    fetcher = config["fetcher"]
    if fetcher:
        try:
            items = fetcher(list_name=list_name, force_fallback=force_fallback)
            if items:
                return items
        except Exception as exc:
            print(
                f"[hub] {config['label']} fetcher failed: {exc}",
                file=sys.stderr,
            )

    # Fall back to docx parser
    if config["supports_docx"] and parse_docx_cache:
        try:
            items = parse_docx_cache(store)
            if items:
                print(
                    f"[hub] {config['label']}: fallback docx parsed {len(items)} items",
                    file=sys.stderr,
                )
                return items
        except Exception as exc:
            print(
                f"[hub] {config['label']} docx fallback failed: {exc}",
                file=sys.stderr,
            )

    return []


def get_all_store_products(
    list_name: str = "Price Comparison",
    force_fallback: bool = False,
) -> dict[str, list[ProductItem]]:
    """Fetch product items from all configured supermarkets.

    Args:
        list_name: Name of the saved list.
        force_fallback: If True, skip live APIs.

    Returns:
        dict mapping store name to list of ``ProductItem`` instances.
    """
    result = {}
    for store in ALL_STORES:
        result[store] = get_store_products(
            store, list_name=list_name, force_fallback=force_fallback
        )
    return result


def get_store_info() -> dict:
    """Return metadata about all configured stores.

    Returns:
        dict mapping store name to config details (label, API support).
    """
    return {
        store: {
            "label": cfg["label"],
            "supports_live_api": cfg["supports_live_api"],
            "supports_docx": cfg["supports_docx"],
        }
        for store, cfg in STORE_REGISTRY.items()
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import pprint

    print("=== Extractor Hub Self-Test ===\n")

    # Info
    print("Store info:")
    pprint.pprint(get_store_info())

    # Test each store
    for store in ALL_STORES:
        print(f"\nFetching {store}...")
        items = get_store_products(store, force_fallback=True)
        print(f"  Found {len(items)} items")
        for item in items[:3]:
            print(f"  - {item.raw_name}: ${item.price:.2f}")

    print("\n=== Done ===")
