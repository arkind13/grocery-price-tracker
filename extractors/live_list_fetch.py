#!/usr/bin/env python3
"""Live snapshot loading for the Wednesday `--source live` path (§4.2).

The live window (session_refresh Phase C) writes per-store snapshot
files under ``data/live_snapshots/``:

    YYYY-MM-DD_ww_pricecompare.json      (WW "Price Compare" list)
    YYYY-MM-DD_ww_speciallist28.json     (WW "Special list (28)" list)
    YYYY-MM-DD_coles_pricecompare.json   (Coles "Price Compare" list)

This module READS those snapshots and converts them into ProductItems —
it is a pure offline loader: no network, no cookies, and no third-party
scraper traffic of any kind (guardrail 5; asserted by grep). Wednesday
Steps 1-2 consume ``snapshots_for_date``; Step 8 specials consume
``specials_from_live``; ``validate_complete`` is the all-or-nothing
gate BEFORE any sheet write (§5.2).

WW snapshot item shape (raw list-API product dicts):
    {"Stockcode": 123456, "DisplayName": "Milk 2L", "Price": 3.5,
     "PackageSize": "2L", "IsOnSpecial": true, "WasPrice": 4.0,
     "SavingsAmount": 0.5, "IsHalfPrice": false, "Brand": "Pura",
     "CupString": "$1.75 / 1L", "Quantity": 2}

A top-level bare list is accepted, or a {"items": [...]} /
{"Items": [...]} wrapper. List "Quantity" NEVER duplicates items —
one product = one ProductItem regardless of the requested quantity.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TRACKER_DIR = _HERE.parent
if str(_TRACKER_DIR) not in sys.path:
    sys.path.insert(0, str(_TRACKER_DIR))

from extractors.models import ProductItem

DATA_DIR = _TRACKER_DIR / "data"
SNAPSHOTS_DIR = DATA_DIR / "live_snapshots"

# Slug constants (predictable for tests; spec §4.6).
WW_PRICECOMPARE_SLUG = "pricecompare"
WW_SPECIALS_SLUG = "speciallist28"
COLES_PRICECOMPARE_SLUG = "pricecompare"

_STORE_SLUGS = {
    "woolworths": (WW_PRICECOMPARE_SLUG, WW_SPECIALS_SLUG),
    "coles": (COLES_PRICECOMPARE_SLUG,),
}


def ww_snapshot_path(date_str: str, slug: str = WW_PRICECOMPARE_SLUG) -> Path:
    """Path of one Woolworths snapshot file for a date."""
    return SNAPSHOTS_DIR / f"{date_str}_ww_{slug}.json"


def coles_snapshot_path(date_str: str) -> Path:
    """Path of the Coles snapshot file for a date."""
    return SNAPSHOTS_DIR / f"{date_str}_coles_{COLES_PRICECOMPARE_SLUG}.json"


def required_snapshot_paths(date_str: str) -> list[Path]:
    """The files that MUST exist for a complete live run (§5.2).

    The WW Special-list snapshot is deliberately NOT required here — a
    missing specials file only degrades Step 8 to the standard
    missing-docs warning (§4.8), it never blocks the sheet write.
    """
    return [
        ww_snapshot_path(date_str, WW_PRICECOMPARE_SLUG),
        coles_snapshot_path(date_str),
    ]


def _load_json_items(path: Path) -> list[dict]:
    """Read one snapshot file as a list of raw product dicts.

    Accepts a bare JSON list or an {"items"|"Items": [...]} wrapper.

    Args:
        path (Path): snapshot file path.

    Returns:
        list[dict]: raw product dicts.

    Raises:
        ValueError: when the file is corrupt / not JSON / wrong shape
        (message names the file — §5.2 wording contract).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Snapshot file unreadable/corrupt: "
                         f"{path.name} ({exc})") from exc
    if isinstance(data, dict):
        data = data.get("items", data.get("Items"))
    if not isinstance(data, list):
        raise ValueError(f"Snapshot file has unexpected shape: "
                         f"{path.name} — expected a JSON list")
    return [d for d in data if isinstance(d, dict)]


def _normalise(name: str) -> str:
    """Lowercase + collapse whitespace (dedup fallback key)."""
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _dedup_key(product_id: str, name: str) -> str:
    """Dedup key: product id when present, else normalised name."""
    return f"id:{product_id}" if product_id else f"name:{_normalise(name)}"


def load_ww_snapshot(path: Path) -> list[ProductItem]:
    """Convert a Woolworths list snapshot into ProductItems.

    Specials semantics mirror the extractor strings: "Was $x.xx" /
    "Half Price" / "Save $x.xx" (from IsOnSpecial / WasPrice /
    SavingsAmount / IsHalfPrice). Dedup by product id across entries
    (fallback: normalised name); a list "Quantity" never duplicates
    items (one product = one ProductItem).

    Args:
        path (Path): snapshot file path.

    Returns:
        list[ProductItem]: deduped items in file order.

    Raises:
        ValueError: when the file is corrupt / wrong shape.
    """
    raw_items = _load_json_items(path)
    products: list[ProductItem] = []
    seen: set[str] = set()
    for item in raw_items:
        name = str(item.get("DisplayName") or item.get("Name") or "").strip()
        if not name:
            continue
        product_id = str(item.get("Stockcode")
                         or item.get("ArticleId")
                         or item.get("ProductId") or "")
        key = _dedup_key(product_id, name)
        if key in seen:
            continue
        seen.add(key)

        try:
            price = float(item.get("Price") or 0.0)
        except (TypeError, ValueError):
            price = 0.0

        is_special = bool(item.get("IsOnSpecial", False))
        is_half_price = bool(item.get("IsHalfPrice", False))
        try:
            was_price = float(item.get("WasPrice") or 0.0)
        except (TypeError, ValueError):
            was_price = 0.0
        try:
            savings = float(item.get("SavingsAmount") or 0.0)
        except (TypeError, ValueError):
            savings = 0.0

        special_desc = ""
        if is_special and was_price > 0:
            special_desc = f"Was ${was_price:.2f}"
        elif is_half_price:
            special_desc = "Half Price"
        elif is_special and savings > 0:
            special_desc = f"Save ${savings:.2f}"

        products.append(ProductItem(
            store="woolworths",
            raw_name=name,
            price=price,
            is_special=is_special,
            special_desc=special_desc,
            unit_price=str(item.get("CupString", "") or ""),
            brand=str(item.get("Brand", "") or ""),
            size=str(item.get("PackageSize", "") or ""),
            product_id=product_id,
        ))
    return products


def load_coles_snapshot(path: Path) -> list[ProductItem]:
    """Convert a Coles list snapshot into ProductItems.

    Reuses coles_extractor._parse_search_result per product dict (the
    saved-list product shape equals the search shape). Dedup by product
    id (fallback: normalised name).

    Args:
        path (Path): snapshot file path.

    Returns:
        list[ProductItem]: deduped items in file order.

    Raises:
        ValueError: when the file is corrupt / wrong shape.
    """
    from extractors.coles_extractor import _parse_search_result

    raw_items = _load_json_items(path)
    products: list[ProductItem] = []
    seen: set[str] = set()
    for item in raw_items:
        # Skip non-product entries (ads, banners) — same rule as search.
        if item.get("_type", "PRODUCT") != "PRODUCT":
            continue
        parsed = _parse_search_result(item)
        if parsed is None:
            continue
        key = _dedup_key(parsed.product_id, parsed.raw_name)
        if key in seen:
            continue
        seen.add(key)
        products.append(parsed)
    return products


def _load_store_snapshots(date_str: str, store: str) -> list[ProductItem]:
    """Load + merge every snapshot file for one store (skips missing).

    Args:
        date_str (str): YYYY-MM-DD.
        store (str): "woolworths" or "coles".

    Returns:
        list[ProductItem]: merged items (deduped across files).
    """
    items: list[ProductItem] = []
    seen: set[str] = set()
    if store == "woolworths":
        paths = [ww_snapshot_path(date_str, WW_PRICECOMPARE_SLUG),
                 ww_snapshot_path(date_str, WW_SPECIALS_SLUG)]
        loader = load_ww_snapshot
    else:
        paths = [coles_snapshot_path(date_str)]
        loader = load_coles_snapshot
    for path in paths:
        if not path.exists():
            continue
        for item in loader(path):
            key = _dedup_key(item.product_id, item.raw_name)
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def snapshots_for_date(date_str: str) -> dict:
    """Load both stores' snapshots for a date (Wednesday Steps 1-2).

    Missing files are skipped (call validate_complete first for the
    all-or-nothing gate); corrupt files raise via the loaders.

    Args:
        date_str (str): YYYY-MM-DD.

    Returns:
        dict: {"woolworths": [ProductItem...], "coles": [ProductItem...]}.
    """
    return {
        "woolworths": _load_store_snapshots(date_str, "woolworths"),
        "coles": _load_store_snapshots(date_str, "coles"),
    }


def specials_from_live(date_str: str) -> list[ProductItem]:
    """Specials for Step 8, from the WW Special-list snapshot only.

    Args:
        date_str (str): YYYY-MM-DD.

    Returns:
        list[ProductItem]: items flagged special. [] when the snapshot
        does not exist (caller falls back to the standard warning).
    """
    path = ww_snapshot_path(date_str, WW_SPECIALS_SLUG)
    if not path.exists():
        return []
    return [i for i in load_ww_snapshot(path) if i.is_special]


def validate_complete(date_str: str) -> None:
    """All-or-nothing completeness gate — raises BEFORE any sheet write.

    Args:
        date_str (str): YYYY-MM-DD.

    Returns:
        None when every required snapshot exists, parses, and is
        non-empty.

    Raises:
        ValueError: naming the exact missing / corrupt / empty file(s)
        (§5.2 clean-stop contract).
    """
    problems: list[str] = []
    for path in required_snapshot_paths(date_str):
        if not path.exists():
            problems.append(f"missing: {path.name}")
            continue
        try:
            items = (load_ww_snapshot(path)
                     if "_ww_" in path.name else load_coles_snapshot(path))
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if not items:
            problems.append(f"empty (no products): {path.name}")
    if problems:
        raise ValueError(
            "Live fetch incomplete — clean stop before any sheet write. "
            "Problems: " + "; ".join(problems) + ". Re-run the live "
            "window (live-refresh) or paste your lists into the Word "
            "docs as before and run wednesday (no flag).")
