#!/usr/bin/env python3
"""Read-only analytics engine over the Products_Master Google Sheet.

Answers aggregate/comparison questions purely from stored prices (Col D =
Woolworths, Col E = Coles), brand (Col G), size (Col C), category (Col B),
specials (Col M/N), rewards (Col O), and keywords (Col P).

Modelled on ``core/specials_reporter.py`` — each public function does ONE
``get_all_values()`` call, is strictly read-only, and returns structured
dicts. Never calls live extractors, never writes to the sheet.
"""
from __future__ import annotations

import re
import sys
from typing import Optional

from core.sheets_sync import PRICE_COL, _find_col

# Price-parsing regex (shared with specials_reporter): matches ``$3.50``,
# ``A$3.50``, or a bare numeric string.
_PRICE_RE = re.compile(r"(?:A\$|\$)\s*(\d+\.?\d*)")

# Stores supported by this analyst (mirrors PRICE_COL after Aldi removal).
_STORES = ("woolworths", "coles")


def _parse_price(cell: str) -> Optional[float]:
    """Parse a price cell into a float, or None if unparseable.

    Args:
        cell: raw sheet cell string (e.g. "$3.50", "A$4.00", "3.5").

    Returns:
        float price, or None.
    """
    if not cell:
        return None
    text = str(cell).strip()
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if m:
        try:
            return float(m.group(1))
        except (ValueError, TypeError):
            return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def _load_rows(worksheet=None) -> tuple[list[str], list[list[str]]]:
    """Connect (if needed) and return (header, data_rows) from the sheet.

    Args:
        worksheet: optional pre-connected gspread worksheet for tests/reuse.

    Returns:
        (header_list, data_rows). Both empty if the sheet is blank.
    """
    if worksheet is None:
        from core.sheets_client import connect_worksheet
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    if not all_values or len(all_values) < 2:
        return [], []
    return all_values[0], all_values[1:]


def _resolve_specials_cols(header: list[str]) -> dict[str, int]:
    """Resolve 0-based specials column indices by header name.

    Args:
        header: the sheet header row.

    Returns:
        dict mapping store -> 0-based column index, for found columns only.
    """
    result = {}
    for store in _STORES:
        header_name = f"{store.capitalize()}_Specials"
        idx = _find_col(header, header_name)
        if idx is not None:
            result[store] = idx
    return result


def top_savings(
    cheaper_store: str,
    pricier_store: str,
    limit: int = 5,
    worksheet=None,
) -> list[dict]:
    """Return top-N items where ``cheaper_store`` is cheaper than
    ``pricier_store``, sorted by absolute $ saving (desc).

    Only rows priced at BOTH stores are considered.

    Args:
        cheaper_store: store id with the lower price (e.g. "woolworths").
        pricier_store: store id with the higher price (e.g. "coles").
        limit: max number of items to return (default 5).
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        list[dict], each: {name, brand, category, cheaper_price,
        pricier_price, saving}. Top ``limit`` by saving.
    """
    header, rows = _load_rows(worksheet)
    if not rows:
        return []

    cat_col = _find_col(header, "Category") or 1
    brand_col = _find_col(header, "Brand_Type") or 6
    cheaper_col = PRICE_COL.get(cheaper_store.lower())
    pricier_col = PRICE_COL.get(pricier_store.lower())
    if cheaper_col is None or pricier_col is None:
        return []

    results = []
    for row in rows:
        if not row or not row[0].strip():
            continue
        cp = _parse_price(row[cheaper_col]) if cheaper_col < len(row) else None
        pp = _parse_price(row[pricier_col]) if pricier_col < len(row) else None
        if cp is None or pp is None or cp >= pp:
            continue
        name = str(row[0]).strip()
        brand = str(row[brand_col]).strip() if brand_col < len(row) else ""
        category = str(row[cat_col]).strip() if cat_col < len(row) else ""
        results.append({
            "name": name,
            "brand": brand,
            "category": category,
            "cheaper_price": round(cp, 2),
            "pricier_price": round(pp, 2),
            "saving": round(pp - cp, 2),
        })

    results.sort(key=lambda r: r["saving"], reverse=True)
    return results[:limit]


def count_home_brands(category: Optional[str] = None, worksheet=None) -> dict:
    """Count Woolworths home-brand items, optionally filtered by category.

    Uses ``woolworths_discounts.is_woolworths_home_brand(name, brand)``.

    Args:
        category: if set, only count rows whose Col B matches (case-insensitive).
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        dict: {total, by_category: {category: count}}.
    """
    from core.woolworths_discounts import is_woolworths_home_brand

    header, rows = _load_rows(worksheet)
    if not rows:
        return {"total": 0, "by_category": {}}

    cat_col = _find_col(header, "Category") or 1
    brand_col = _find_col(header, "Brand_Type") or 6
    cat_filter = category.lower().strip() if category else None

    total = 0
    by_category: dict[str, int] = {}
    for row in rows:
        if not row or not row[0].strip():
            continue
        name = str(row[0]).strip()
        brand = str(row[brand_col]).strip() if brand_col < len(row) else ""
        row_cat = str(row[cat_col]).strip() if cat_col < len(row) else ""
        if cat_filter and row_cat.lower() != cat_filter:
            continue
        if is_woolworths_home_brand(name, brand):
            total += 1
            by_category[row_cat or "Uncategorised"] = (
                by_category.get(row_cat or "Uncategorised", 0) + 1
            )

    return {"total": total, "by_category": by_category}


def store_only_availability(store: str, worksheet=None) -> list[dict]:
    """Return items priced at ``store`` but NOT at the other store.

    Args:
        store: store id (e.g. "woolworths").
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        list[dict], each: {name, brand, category, price, store}.
    """
    header, rows = _load_rows(worksheet)
    if not rows:
        return []

    cat_col = _find_col(header, "Category") or 1
    brand_col = _find_col(header, "Brand_Type") or 6
    store_lower = store.lower()
    store_col = PRICE_COL.get(store_lower)
    other_stores = [s for s in _STORES if s != store_lower]
    if store_col is None:
        return []

    results = []
    for row in rows:
        if not row or not row[0].strip():
            continue
        sp = _parse_price(row[store_col]) if store_col < len(row) else None
        if sp is None:
            continue
        # Must NOT have a price at the other store
        has_other = False
        for other in other_stores:
            oc = PRICE_COL.get(other)
            if oc is not None and oc < len(row):
                op = _parse_price(row[oc])
                if op is not None:
                    has_other = True
                    break
        if has_other:
            continue
        name = str(row[0]).strip()
        brand = str(row[brand_col]).strip() if brand_col < len(row) else ""
        category = str(row[cat_col]).strip() if cat_col < len(row) else ""
        results.append({
            "name": name,
            "brand": brand,
            "category": category,
            "price": round(sp, 2),
            "store": store_lower,
        })

    return results


def total_basket_savings(
    store_a: str,
    store_b: str,
    worksheet=None,
) -> dict:
    """Compute total basket savings between two stores for items priced at both.

    Args:
        store_a: first store id.
        store_b: second store id.
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        dict: {items_compared, total_at_a, total_at_b, saving}.
        ``saving`` is total_at_b - total_at_a (positive if store_a is cheaper).
    """
    header, rows = _load_rows(worksheet)
    if not rows:
        return {
            "items_compared": 0,
            "total_at_a": 0.0,
            "total_at_b": 0.0,
            "saving": 0.0,
        }

    col_a = PRICE_COL.get(store_a.lower())
    col_b = PRICE_COL.get(store_b.lower())
    if col_a is None or col_b is None:
        return {
            "items_compared": 0,
            "total_at_a": 0.0,
            "total_at_b": 0.0,
            "saving": 0.0,
        }

    items = 0
    total_a = 0.0
    total_b = 0.0
    for row in rows:
        if not row or not row[0].strip():
            continue
        pa = _parse_price(row[col_a]) if col_a < len(row) else None
        pb = _parse_price(row[col_b]) if col_b < len(row) else None
        if pa is None or pb is None:
            continue
        items += 1
        total_a += pa
        total_b += pb

    return {
        "items_compared": items,
        "total_at_a": round(total_a, 2),
        "total_at_b": round(total_b, 2),
        "saving": round(total_b - total_a, 2),
    }


def category_breakdown(worksheet=None) -> list[dict]:
    """Return item count per Col B category, sorted by count (desc).

    Args:
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        list[dict], each: {category, count}.
    """
    header, rows = _load_rows(worksheet)
    if not rows:
        return []

    cat_col = _find_col(header, "Category") or 1
    counts: dict[str, int] = {}
    for row in rows:
        if not row or not row[0].strip():
            continue
        cat = str(row[cat_col]).strip() if cat_col < len(row) else ""
        key = cat or "Uncategorised"
        counts[key] = counts.get(key, 0) + 1

    result = [{"category": k, "count": v} for k, v in counts.items()]
    result.sort(key=lambda r: r["count"], reverse=True)
    return result


def count_specials(store: Optional[str] = None, worksheet=None) -> int:
    """Count items on special at ``store`` (non-empty specials cell).

    Args:
        store: "woolworths"|"coles"|None. If None, count across both stores.
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        int count of rows with a non-empty specials cell.
    """
    header, rows = _load_rows(worksheet)
    if not rows:
        return 0

    specials_cols = _resolve_specials_cols(header)
    if not specials_cols:
        return 0

    store_lower = store.lower() if store else None
    target_cols = []
    for s, col in specials_cols.items():
        if store_lower and s != store_lower:
            continue
        target_cols.append(col)

    count = 0
    for row in rows:
        if not row or not row[0].strip():
            continue
        for col in target_cols:
            if col < len(row) and row[col].strip():
                count += 1
                break  # one special per row is enough
    return count


def count_rewards(worksheet=None) -> int:
    """Count items with bonus rewards (non-empty Col O).

    Args:
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        int count of rows with a non-empty Rewards_Points cell.
    """
    header, rows = _load_rows(worksheet)
    if not rows:
        return 0

    rewards_col = _find_col(header, "Rewards_Points")
    if rewards_col is None:
        return 0

    count = 0
    for row in rows:
        if not row or not row[0].strip():
            continue
        if rewards_col < len(row) and row[rewards_col].strip():
            count += 1
    return count
