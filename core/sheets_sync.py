#!/usr/bin/env python3
"""Headless Google Sheets batch sync and single-item price updater.

Consumes MatchResult objects (Phase 2) and ProductItem objects (Phase 1).
Writes prices (D/E/F), specials (M/N), rewards (O), and timestamps (H)
to Products_Master.
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Bootstrap
_HERE = Path(__file__).resolve().parent  # core/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from gspread.exceptions import APIError

from core.sheets_client import connect_worksheet
from core.name_matcher import KeywordIndex  # for _normalize reuse

# ============================================================================
# Section A: Column map + constants
# ============================================================================

# 0-based indices into Products_Master row (positional, locked)
PRICE_COL = {"woolworths": 3, "coles": 4, "aldi": 5}   # D, E, F
LAST_UPDATED_COL = 7                                     # H
ALDI_REFRESH_COL = 11                                    # L (legacy; untouched)

# Header-driven (resolved at runtime; written only if present)
SPECIALS_HEADER_BY_STORE = {
    "woolworths": "Woolworths_Specials",   # M when present
    "coles": "Coles_Specials",             # N when present
}
REWARDS_HEADER = "Rewards_Points"          # O when present

# ============================================================================
# Section B: Helpers (timestamp, column resolution, padding, backoff)
# ============================================================================


def _normalize_header(s: str) -> str:
    """Lowercase, trim, collapse whitespace — for header comparison.
    Underscores are treated as whitespace to allow lenient matching."""
    normalized = str(s).strip().lower()
    normalized = normalized.replace("_", " ")
    return re.sub(r"\s+", " ", normalized)


def _sydney_now_str() -> str:
    """Return now in Australia/Sydney as 'YYYY-MM-DD HH:MM'.

    Uses stdlib zoneinfo (Python 3.9+). Falls back to UTC+'Z' if tzdata missing.
    """
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Australia/Sydney"))
        return now.strftime("%Y-%m-%d %H:%M")
    except Exception:
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%d %H:%M") + "Z"


def _find_col(header: list, name: str) -> Optional[int]:
    """Return 0-based index of header matching name (case-insensitive,
    whitespace-normalized), else None."""
    normalized_target = _normalize_header(name)
    for i, h in enumerate(header):
        if _normalize_header(h) == normalized_target:
            return i
    return None


def _col_letter(idx: int) -> str:
    """0-based index -> spreadsheet column letter (0->A, 25->Z, 26->AA)."""
    if idx < 26:
        return chr(65 + idx)
    return _col_letter(idx // 26 - 1) + _col_letter(idx % 26)


def _pad_rows(rows: list, width: int) -> None:
    """In-place pad every row to `width` with '' (never shrink)."""
    for row in rows:
        while len(row) < width:
            row.append("")


def _update_with_backoff(worksheet, rows, range_name, *,
                         max_retries: int = 4, base_delay: float = 1.0):
    """Exponential backoff on HTTP 429. Re-raise after max_retries or on non-429."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            worksheet.update(values=rows, range_name=range_name)
            return
        except APIError as exc:
            last_exc = exc
            status = getattr(exc, "status", None)
            if status == 429 and attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
    raise last_exc


# ============================================================================
# Section C: Report dataclass
# ============================================================================


@dataclass(frozen=True)
class SyncReport:
    """Outcome of a batch sync run against Products_Master."""
    rows_examined: int
    rows_updated: int
    items_matched: int
    items_skipped: int
    stores_synced: list = field(default_factory=list)
    range_written: str = ""
    timestamp: str = ""
    dry_run: bool = False
    warnings: list = field(default_factory=list)


# ============================================================================
# Section D: Batch sync
# ============================================================================


def sync_prices(
    results: list,
    items: list,
    *,
    dry_run: bool = False,
    worksheet=None,
) -> SyncReport:
    """Atomically sync matched prices/specials/rewards to Products_Master.

    Args:
        results: MatchResult list from NameMatcher.match_batch(items).
            results[i] corresponds to items[i]. MUST be same length & order.
        items: the source ProductItem list (carries price/specials/rewards).
        dry_run: if True, compute & print planned changes, write nothing.
        worksheet: optional pre-connected worksheet. If None, connects fresh.

    Returns:
        SyncReport summarizing what was (or would be) written.

    Behavior:
        1. assert len(results) == len(items) (defensive).
        2. Connect worksheet if None.
        3. all_values = worksheet.get_all_values()  # ONE read.
           header = all_values[0]; rows = copy.deepcopy(all_values[1:]).
        4. Resolve specials/rewards column indices by header name.
        5. ts = _sydney_now_str().
        6. For each (result, item) in zip(results, items):
             - if not matched or row_index is None: skip, items_skipped++.
             - list_idx = result.row_index - 2. Bounds-check.
             - Write price to PRICE_COL[store], specials (if resolved),
               rewards (if resolved), timestamp to LAST_UPDATED_COL.
        7. Pad ALL rows to target_width.
        8. If dry_run: print summary, return report (no write).
        9. Else: range_name = f"A2:{_col_letter(target_width-1)}{len(rows)+1}";
           _update_with_backoff(worksheet, rows, range_name).
        10. Return report. Never raise on a single unmatched item.
    """
    assert len(results) == len(items), "results and items must be same length"

    if worksheet is None:
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    header = all_values[0]
    rows = copy.deepcopy(all_values[1:])
    rows_examined = len(rows)

    # Resolve specials columns by header name
    specials_col: dict[str, int] = {}
    report_warnings: list[str] = []
    for store_key, header_name in SPECIALS_HEADER_BY_STORE.items():
        idx = _find_col(header, header_name)
        if idx is not None:
            specials_col[store_key] = idx
        else:
            report_warnings.append(
                f"{header_name} column absent - specials not written for {store_key}"
            )

    # Resolve rewards column
    rewards_col = _find_col(header, REWARDS_HEADER)
    if rewards_col is None:
        report_warnings.append(
            "Rewards_Points column absent - rewards not written"
        )

    ts = _sydney_now_str()
    rows_updated = 0
    items_matched = 0
    items_skipped = 0
    stores_synced_set: set[str] = set()

    # Pre-pad rows to minimum required width before writing
    min_write_width = max(
        max(PRICE_COL.values()) + 1,
        LAST_UPDATED_COL + 1,
        max(specials_col.values()) + 1 if specials_col else 0,
        (rewards_col + 1) if rewards_col is not None else 0,
    )
    _pad_rows(rows, min_write_width)

    for result, item in zip(results, items):
        if not result.matched or result.row_index is None:
            items_skipped += 1
            continue

        list_idx = result.row_index - 2
        if list_idx < 0 or list_idx >= len(rows):
            continue  # defensive bounds check

        row = rows[list_idx]
        row[PRICE_COL[result.store]] = item.price

        if result.store in specials_col:
            row[specials_col[result.store]] = (
                item.special_desc if item.is_special else ""
            )

        if rewards_col is not None:
            row[rewards_col] = item.rewards_points or ""

        row[LAST_UPDATED_COL] = ts
        rows_updated += 1
        items_matched += 1
        stores_synced_set.add(result.store)

    # Compute final target width
    target_width = max(
        max(len(r) for r in rows) if rows else 0,
        max(PRICE_COL.values()) + 1,
        max(specials_col.values()) + 1 if specials_col else 0,
        (rewards_col + 1) if rewards_col is not None else 0,
        LAST_UPDATED_COL + 1,
        len(header),
    )
    _pad_rows(rows, target_width)

    if dry_run:
        print(
            f"[DRY RUN] sync_prices: matched={items_matched} "
            f"skipped={items_skipped} rows_to_update={rows_updated}"
        )
        print(
            f"          stores={sorted(stores_synced_set)} ts={ts}"
        )
        print(
            f"          planned_range="
            f"A2:{_col_letter(target_width - 1)}{len(rows) + 1} "
            f"warnings={report_warnings}"
        )
        return SyncReport(
            rows_examined=rows_examined,
            rows_updated=rows_updated,
            items_matched=items_matched,
            items_skipped=items_skipped,
            stores_synced=sorted(stores_synced_set),
            range_written="",
            timestamp=ts,
            dry_run=True,
            warnings=report_warnings,
        )

    range_name = f"A2:{_col_letter(target_width - 1)}{len(rows) + 1}"
    _update_with_backoff(worksheet, rows, range_name)
    return SyncReport(
        rows_examined=rows_examined,
        rows_updated=rows_updated,
        items_matched=items_matched,
        items_skipped=items_skipped,
        stores_synced=sorted(stores_synced_set),
        range_written=range_name,
        timestamp=ts,
        dry_run=False,
        warnings=report_warnings,
    )


# ============================================================================
# Section E: Single-item updater
# ============================================================================


def update_single_price(
    product_name: str,
    store: str,
    price: float,
    *,
    dry_run: bool = False,
    worksheet=None,
) -> dict:
    """Update ONE price cell by generic name (Col A) or store keyword (Col I/J/K).

    Args:
        product_name: generic name to find in Col A (exact, case-insensitive,
            whitespace-normalized via KeywordIndex._normalize), falling back
            to the store's keyword col (Col I/J/K via STORE_KEYWORD_COL).
        store: "woolworths"|"coles"|"aldi".
        price: new price (float). Must be > 0.
        dry_run: if True, report old/new without writing.
        worksheet: optional pre-connected worksheet.

    Returns:
        dict with keys:
            found, row_index, store, old_price, new_price, wrote,
            range_written, error

    Behavior:
        1. Validate store in PRICE_COL; validate price > 0 (fail fast).
        2. Connect worksheet if None.
        3. all_values = worksheet.get_all_values() (ONE read).
        4. Find first data row whose Col A (idx 0) OR the store's keyword
           col (Col I/J/K via STORE_KEYWORD_COL) normalizes equal; Col A wins.
        5. If not found: return {found: False, error: "product not found", ...}.
        6. Parse old_price from row[PRICE_COL[store]].
        7. If dry_run: return found/old/new, wrote=False.
        8. Else: read the full row, mutate price cell + H timestamp cell,
           write the single row back via _update_with_backoff.
        9. Return result dict with wrote=True, range_written set.
    """
    store_lower = store.lower()

    # --- fail-fast validation ---
    if store_lower not in PRICE_COL:
        return {
            "found": False,
            "row_index": None,
            "store": store_lower,
            "old_price": None,
            "new_price": price,
            "wrote": False,
            "range_written": "",
            "error": f"unknown store: {store}",
        }

    if price <= 0:
        return {
            "found": False,
            "row_index": None,
            "store": store_lower,
            "old_price": None,
            "new_price": price,
            "wrote": False,
            "range_written": "",
            "error": "price must be > 0",
        }

    # --- connect & read ---
    if worksheet is None:
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    rows = all_values[1:]  # skip header

    target_normalized = KeywordIndex._normalize(product_name)
    # Per-store keyword col (Col I/J/K) — fallback match target.
    kw_col = STORE_KEYWORD_COL.get(store_lower)

    found_idx: Optional[int] = None
    row_data: Optional[list] = None
    for i, row in enumerate(rows):
        # Step 1: exact match on Col A (generic name) — takes priority.
        if len(row) > 0 and KeywordIndex._normalize(row[0]) == target_normalized:
            found_idx = i
            row_data = row
            break
        # Step 2: match on this store's keyword col (Col I/J/K) via the
        # per-store keyword map (woolworths=8/coles=9/aldi=10). Fixes
        # DEFECT-1: rows whose Col A differs from the Word-doc name but
        # whose store keyword matches now resolve correctly.
        if (
            kw_col is not None
            and len(row) > kw_col
            and row[kw_col]
            and KeywordIndex._normalize(row[kw_col]) == target_normalized
        ):
            found_idx = i
            row_data = row
            break

    if found_idx is None:
        return {
            "found": False,
            "row_index": None,
            "store": store_lower,
            "old_price": None,
            "new_price": price,
            "wrote": False,
            "range_written": "",
            "error": "product not found",
        }

    sheet_row = found_idx + 2  # 1-based
    price_col = PRICE_COL[store_lower]

    # Parse old price
    old_price: Optional[float] = None
    if len(row_data) > price_col and row_data[price_col]:
        try:
            # Try regex: (?:A\$|\$)\s*(\d+\.\d+)
            m = re.search(r"(?:A\$|\$)\s*(\d+\.\d+)", str(row_data[price_col]))
            old_price = float(m.group(1)) if m else float(row_data[price_col])
        except (ValueError, TypeError):
            old_price = None

    if dry_run:
        return {
            "found": True,
            "row_index": sheet_row,
            "store": store_lower,
            "old_price": old_price,
            "new_price": price,
            "wrote": False,
            "range_written": "",
            "error": "",
        }

    # --- live write ---
    ts = _sydney_now_str()
    full_row = list(row_data)  # make mutable copy
    target_width = max(price_col + 1, LAST_UPDATED_COL + 1)
    while len(full_row) < target_width:
        full_row.append("")
    full_row[price_col] = price
    full_row[LAST_UPDATED_COL] = ts
    # Truncate to target_width — the sheet row has 16 cols (A-P) but we only
    # write up to LAST_UPDATED_COL; gspread rejects writing past the range.
    full_row = full_row[:target_width]

    range_name = f"A{sheet_row}:{_col_letter(target_width - 1)}{sheet_row}"
    _update_with_backoff(worksheet, [full_row], range_name)

    return {
        "found": True,
        "row_index": sheet_row,
        "store": store_lower,
        "old_price": old_price,
        "new_price": price,
        "wrote": True,
        "range_written": range_name,
        "error": "",
    }


def mark_not_available(
    product_name: str,
    store: str,
    worksheet=None,
    dry_run: bool = False,
) -> dict:
    """Mark a product as not available at a store (Phase 9.6 `na` action).

    Writes the literal "NA" to BOTH the store's keyword column (Col I/J/K)
    and the store's price column (Col D/E/F) for the matched row. The
    keyword col becoming non-empty ("NA") permanently excludes the row from
    the wool/coles missing lists (which key on keyword-col asymmetry); the
    price col "NA" makes the unavailability visible in the sheet.

    Row matching reuses the same two-step strategy as update_single_price:
    exact Col A match first, then the store's keyword col (Col I/J/K).

    Args:
        product_name (str): Generic name (Col A) or store keyword to match.
        store (str): "woolworths" | "coles" | "aldi".
        worksheet: Open gspread worksheet; connected if None.
        dry_run (bool): If True, return the planned write without mutating.

    Returns:
        dict: {found, row_index, store, wrote, range_written, error}.
    """
    store_lower = (store or "").strip().lower()
    if store_lower not in PRICE_COL:
        return {
            "found": False,
            "row_index": None,
            "store": store_lower,
            "wrote": False,
            "range_written": "",
            "error": f"unknown store: {store}",
        }

    if worksheet is None:
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    rows = all_values[1:]  # skip header

    target_normalized = KeywordIndex._normalize(product_name)
    kw_col = STORE_KEYWORD_COL.get(store_lower)
    price_col = PRICE_COL[store_lower]

    found_idx: Optional[int] = None
    row_data: Optional[list] = None
    for i, row in enumerate(rows):
        # Step 1: exact match on Col A (generic name).
        if len(row) > 0 and KeywordIndex._normalize(row[0]) == target_normalized:
            found_idx = i
            row_data = row
            break
        # Step 2: match on this store's keyword col (Col I/J/K).
        if (
            kw_col is not None
            and len(row) > kw_col
            and row[kw_col]
            and KeywordIndex._normalize(row[kw_col]) == target_normalized
        ):
            found_idx = i
            row_data = row
            break

    if found_idx is None:
        return {
            "found": False,
            "row_index": None,
            "store": store_lower,
            "wrote": False,
            "range_written": "",
            "error": "product not found",
        }

    sheet_row = found_idx + 2  # 1-based

    if dry_run:
        return {
            "found": True,
            "row_index": sheet_row,
            "store": store_lower,
            "wrote": False,
            "range_written": "",
            "error": "",
        }

    # Live write: "NA" into both the keyword col and the price col.
    full_row = list(row_data)  # make mutable copy
    target_width = max(price_col + 1, LAST_UPDATED_COL + 1)
    if kw_col is not None:
        target_width = max(target_width, kw_col + 1)
    while len(full_row) < target_width:
        full_row.append("")
    full_row[price_col] = "NA"
    if kw_col is not None:
        full_row[kw_col] = "NA"
    full_row[LAST_UPDATED_COL] = _sydney_now_str()
    # Truncate to target_width so the range write doesn't overflow into
    # columns past target_width (the sheet has 16 cols A-P but we only
    # write up to the keyword col; gspread rejects writing past the range).
    full_row = full_row[:target_width]

    range_name = f"A{sheet_row}:{_col_letter(target_width - 1)}{sheet_row}"
    _update_with_backoff(worksheet, [full_row], range_name)

    return {
        "found": True,
        "row_index": sheet_row,
        "store": store_lower,
        "wrote": True,
        "range_written": range_name,
        "error": "",
    }


def set_store_keyword(product_name, store, keyword, worksheet=None, dry_run=False):
    """Write a store keyword (Col I/J/K) for an existing sheet row.

    The user manually provides the exact store product name when live search
    returns nothing. This writes that name to the store's keyword column
    (Col I for woolworths, J for coles, K for aldi) so the row is matched on
    next sync.

    Args:
        product_name: Generic name (Col A) or existing keyword to match.
        store: "woolworths" | "coles" | "aldi".
        keyword: The store's product name to save.
        worksheet: Open gspread worksheet; connected if None.
        dry_run: If True, return planned write without mutating.

    Returns:
        dict: {found, row_index, store, wrote, range_written, error}
    """
    store_lower = (store or "").strip().lower()
    if store_lower not in PRICE_COL:
        return {"found": False, "error": f"unknown store: {store}"}

    if worksheet is None:
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    rows = all_values[1:]

    target_normalized = KeywordIndex._normalize(product_name)
    kw_col = STORE_KEYWORD_COL.get(store_lower)
    price_col = PRICE_COL[store_lower]

    found_idx = None
    row_data = None
    for i, row in enumerate(rows):
        if len(row) > 0 and KeywordIndex._normalize(row[0]) == target_normalized:
            found_idx = i
            row_data = row
            break
        if (kw_col is not None and len(row) > kw_col and row[kw_col]
                and KeywordIndex._normalize(row[kw_col]) == target_normalized):
            found_idx = i
            row_data = row
            break

    if found_idx is None:
        return {"found": False, "error": "product not found"}

    sheet_row = found_idx + 2

    if dry_run:
        return {"found": True, "row_index": sheet_row, "store": store_lower,
                "wrote": False, "range_written": "", "error": ""}

    full_row = list(row_data)
    target_width = max(kw_col + 1, LAST_UPDATED_COL + 1)
    while len(full_row) < target_width:
        full_row.append("")
    full_row[kw_col] = keyword
    full_row[LAST_UPDATED_COL] = _sydney_now_str()
    full_row = full_row[:target_width]

    range_name = f"A{sheet_row}:{_col_letter(target_width - 1)}{sheet_row}"
    _update_with_backoff(worksheet, [full_row], range_name)

    return {"found": True, "row_index": sheet_row, "store": store_lower,
            "wrote": True, "range_written": range_name, "error": ""}


# ============================================================================
# Section E2: Add new product row (auto-add from live search)
# ============================================================================

# Store keyword column map (Col I/J/K) for add_product_row
STORE_KEYWORD_COL = {"woolworths": 8, "coles": 9, "aldi": 10}

# Keywords header for Col P (user-side aliases)
KEYWORDS_HEADER = "Keywords"


def add_product_row(
    generic_name: str,
    store: str,
    price: float,
    *,
    brand: str = "",
    size: str = "",
    category: str = "",
    store_keyword: str = "",
    alias: str = "",
    dry_run: bool = False,
    worksheet=None,
) -> dict:
    """Append a new product row to the bottom of Products_Master.

    Used by the lookup engine Step 5 auto-add: when a live search result
    is confirmed by the user, a new row is written with the generic name,
    the store's price (Col D/E/F), brand (Col G), timestamp (Col H), the
    store keyword (Col I/J/K), and optionally the user query as a Col P
    alias.

    Args:
        generic_name: the product name for Col A.
        store: "woolworths"|"coles"|"aldi" — which price column to fill.
        price: numeric price (must be > 0).
        brand: brand string for Col G (default "").
        size: size string for Col C (default "").
        category: category string for Col B (default "").
        store_keyword: the store's exact product name for Col I/J/K
            (default "" — leave the keyword cell empty).
        alias: the user's original query to persist as a Col P alias
            (default "" — no alias written).
        dry_run: if True, report the planned row without writing.
        worksheet: optional pre-connected worksheet.

    Returns:
        dict with keys: wrote, row_index, range_written, error.
    """
    store_lower = store.lower()

    # --- fail-fast validation ---
    if store_lower not in PRICE_COL:
        return {
            "wrote": False, "row_index": None, "range_written": "",
            "error": f"unknown store: {store}",
        }
    if not generic_name or not generic_name.strip():
        return {
            "wrote": False, "row_index": None, "range_written": "",
            "error": "generic_name is required",
        }
    if price <= 0:
        return {
            "wrote": False, "row_index": None, "range_written": "",
            "error": "price must be > 0",
        }

    # --- connect & read ---
    if worksheet is None:
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    header = all_values[0] if all_values else []
    data_rows = all_values[1:] if len(all_values) > 1 else []

    new_row_index = len(data_rows) + 2  # 1-based (row 1 = header)
    price_col = PRICE_COL[store_lower]
    kw_col = STORE_KEYWORD_COL.get(store_lower)
    keywords_col = _find_col(header, KEYWORDS_HEADER)

    # Build the new row
    target_width = max(
        price_col + 1,
        LAST_UPDATED_COL + 1,
        (kw_col + 1) if kw_col is not None else 0,
        (keywords_col + 1) if keywords_col is not None else 0,
        len(header),
    )
    new_row: list = [""] * target_width
    new_row[0] = generic_name.strip()             # Col A
    if category:
        new_row[1] = category                      # Col B
    if size:
        new_row[2] = size                          # Col C
    new_row[price_col] = price                     # Col D/E/F
    new_row[6] = brand                             # Col G
    new_row[LAST_UPDATED_COL] = _sydney_now_str()  # Col H
    if kw_col is not None and store_keyword:
        new_row[kw_col] = store_keyword            # Col I/J/K
    if keywords_col is not None and alias:
        new_row[keywords_col] = alias              # Col P

    if dry_run:
        return {
            "wrote": False, "row_index": new_row_index,
            "range_written": "", "error": "",
        }

    range_name = f"A{new_row_index}:{_col_letter(target_width - 1)}{new_row_index}"
    _update_with_backoff(worksheet, [new_row], range_name)

    return {
        "wrote": True, "row_index": new_row_index,
        "range_written": range_name, "error": "",
    }


# ============================================================================
# Section F: CLI (__main__)
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Google Sheets batch sync and single-item updater"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Read sheet and report planned changes without writing",
    )
    args = parser.parse_args()

    try:
        ws = connect_worksheet()
        all_values = ws.get_all_values()
        header = all_values[0] if all_values else []
        data_rows = all_values[1:] if len(all_values) > 1 else []
        print(f"Rows in sheet: {len(data_rows)}")
        print(f"Columns: {len(header)}")

        # Resolve column locations
        specials_resolved = {}
        for store_key, header_name in SPECIALS_HEADER_BY_STORE.items():
            idx = _find_col(header, header_name)
            if idx is not None:
                specials_resolved[store_key] = idx
                print(f"  {header_name} -> col {idx} ({_col_letter(idx)})")
            else:
                print(f"  {header_name} -> NOT FOUND")

        rewards_idx = _find_col(header, REWARDS_HEADER)
        if rewards_idx is not None:
            print(f"  {REWARDS_HEADER} -> col {rewards_idx} ({_col_letter(rewards_idx)})")
        else:
            print(f"  {REWARDS_HEADER} -> NOT FOUND")

        if args.dry_run:
            print("\n[Dry-run mode] No data written.")
        else:
            print("\n[Live mode] Connected. Use sync_prices() to write data.")

        sys.exit(0)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
