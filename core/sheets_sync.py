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
from core.name_matcher import KeywordIndex, _SIZE_PATTERN  # _normalize reuse + size parse

# ============================================================================
# Section A: Column map + constants
# ============================================================================

# 0-based indices into Products_Master row (positional, locked)
PRICE_COL = {"woolworths": 3, "coles": 4}   # D, E
SIZE_COL = 2                                             # C (unit column)
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
    # Overwrite semantics (2026-09-02): counters + names for the two
    # price-less markers written during a sync.
    unavailable_written: int = 0      # listed, but site gave no price
    notfound_written: int = 0         # mapped row absent from the list
    unavailable_items: list = field(default_factory=list)
    notfound_items: list = field(default_factory=list)


# Marker prefixes written into D/E when a price is unusable. The date
# suffix anchors the no-price "weeks" aging and is PRESERVED across
# marker rewrites (only a returning real price clears it).
_UNAVAILABLE_PREFIX = "unavailable"
_NA_PREFIX = "N/A"

# GONE (2026-09-03, user rule): the user types GONE into a price cell
# (D/E) to say "verified unavailable at this store — never capture on
# missed pricing again". Marker writes (N/A / unavailable) must NEVER
# stomp it; a returning REAL price may (the item resurrected).
_GONE_MARKER = "GONE"


def _is_gone(cell) -> bool:
    """Is this price cell the user's manual GONE verdict?"""
    return str(cell if cell is not None else "").strip().upper() == _GONE_MARKER


def _marker_date(cell: str) -> str:
    """Extract the embedded YYYY-MM-DD anchor from a marker cell ('')."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(cell or ""))
    return m.group(1) if m else ""


def _build_marker(prefix: str, current_cell: str, today: str) -> str:
    """Build a marker cell, preserving any existing date anchor.

    Keeps the OLDEST anchor across marker transitions (N/A ->
    unavailable etc.) so the no-price week count never resets while an
    item stays price-less.

    Args:
        prefix (str): "N/A" or "unavailable".
        current_cell (str): the cell's current content.
        today (str): today's date (YYYY-MM-DD) when no anchor exists.

    Returns:
        str: e.g. "N/A 2026-09-02".
    """
    date = _marker_date(current_cell)
    return f"{prefix} {date or today}"


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
    today = ts[:10]
    rows_updated = 0
    items_matched = 0
    items_skipped = 0
    stores_synced_set: set[str] = set()
    unavailable_written = 0
    unavailable_items: list[str] = []
    # Rows SEEN in a store's list this run (list_idx per store) — the
    # not-found pass marks every OTHER mapped row for that store.
    found_rows: dict[str, set] = {"woolworths": set(), "coles": set()}
    # Stores whose list was provided this run (any parsed item). A
    # store with no items (parse failure / not pasted) never gets
    # not-found marking — absence of the LIST is not absence of items.
    stores_provided: set[str] = {
        str(getattr(i, "store", "") or "").strip().lower()
        for i in items
        if str(getattr(i, "store", "") or "").strip()
    }

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
        store_key = str(result.store).strip().lower()
        found_rows.setdefault(store_key, set()).add(list_idx)

        # Overwrite semantics (2026-09-02): a listed item whose price
        # is unusable (0 / None) NEVER keeps a stale price — the cell
        # becomes "unavailable <date>" (date anchors no-price aging).
        # GONE exception (2026-09-03): a manual GONE verdict is never
        # stomped by a marker — only a returning real price clears it.
        price_val = getattr(item, "price", None)
        if price_val is None or float(price_val) <= 0:
            cell = str(row[PRICE_COL[result.store]]).strip()
            if not _is_gone(cell):
                new_marker = _build_marker(
                    _UNAVAILABLE_PREFIX, cell, today)
                if cell != new_marker:
                    unavailable_written += 1
                    unavailable_items.append(
                        str(row[0]).strip() if row else "")
                row[PRICE_COL[result.store]] = new_marker
        else:
            row[PRICE_COL[result.store]] = item.price

        # Rule B/C.1: heal a blank Col C in the same batch write —
        # live item size first, then parse from the item's raw name.
        # NEVER writes the marker; a non-empty Col C is untouched
        # (D-U3 / spec §5.3). Rows are pre-padded to width >= 8, so
        # Col C (index 2) is always inside the written range.
        col_c = (str(row[SIZE_COL]).strip()
                 if len(row) > SIZE_COL else "")
        if not col_c:
            live_size = str(getattr(item, "size", "") or "").strip()
            if not live_size:
                m = _SIZE_PATTERN.search(
                    str(getattr(item, "raw_name", "") or ""))
                live_size = m.group(1).strip() if m else ""
            if live_size:
                row[SIZE_COL] = live_size

        if result.store in specials_col:
            # D25: M/N hold exactly one of no/discount/multi-buy; "no"
            # overwrites stale free text on every matched row. Unmatched
            # rows keep their old cells (same semantics as prices).
            from extractors.specials_parser import classify_special
            row[specials_col[result.store]] = classify_special(
                bool(item.is_special), str(item.special_desc or ""))

        if rewards_col is not None:
            row[rewards_col] = item.rewards_points or ""

        row[LAST_UPDATED_COL] = ts
        rows_updated += 1
        items_matched += 1
        stores_synced_set.add(result.store)

    # --- Not-found pass (2026-09-02 overwrite semantics) ---------------
    # For every store whose list was provided this run: a MAPPED row
    # (keyword present, not the literal "NA") whose item did NOT appear
    # in the list is "not found" — its price cell becomes "N/A <date>"
    # (stale prices never linger). Rows already carrying today's-or-
    # older marker keep their anchor date so week aging never resets.
    notfound_written = 0
    notfound_items: list[str] = []
    for store_key, kw_col in STORE_KEYWORD_COL.items():
        if store_key not in stores_provided:
            report_warnings.append(
                f"{store_key} list not provided - not-found marking "
                f"skipped for that store")
            continue
        price_col = PRICE_COL[store_key]
        seen = found_rows.get(store_key, set())
        for list_idx, row in enumerate(rows):
            if len(row) <= max(kw_col, price_col):
                continue
            kw = str(row[kw_col]).strip()
            if not kw:
                continue  # unmapped for this store — no data source
            na_row = kw.upper() == "NA"
            seen_now = list_idx in seen
            if not na_row and not seen_now:
                cell = str(row[price_col]).strip()
                if not (_is_gone(cell) or
                        cell.startswith(_UNAVAILABLE_PREFIX) or
                        cell.startswith(_NA_PREFIX)):
                    row[price_col] = _build_marker(_NA_PREFIX, cell, today)
                    row[LAST_UPDATED_COL] = ts
                    notfound_written += 1
                    notfound_items.append(str(row[0]).strip())
            # D25 invariant (2026-09-02): every row trackable at this
            # store holds exactly one of no/discount/multi-buy after a
            # sync. Absent-from-list rows are not on special → "no"
            # (stale "discount"/"multi-buy" from prior weeks clears);
            # deliberately-NA rows normalize blanks to "no" once. Rows
            # seen in the list keep the fresh value the match loop
            # just wrote.
            if not seen_now:
                sc = specials_col.get(store_key)
                if sc is not None and len(row) > sc and \
                        str(row[sc]).strip().lower() != "no":
                    row[sc] = "no"

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
            f"          would mark unavailable={unavailable_written} "
            f"not-found N/A={notfound_written}"
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
            unavailable_written=unavailable_written,
            notfound_written=notfound_written,
            unavailable_items=unavailable_items,
            notfound_items=notfound_items,
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
        unavailable_written=unavailable_written,
        notfound_written=notfound_written,
        unavailable_items=unavailable_items,
        notfound_items=notfound_items,
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
    is_special: Optional[bool] = None,
    special_desc: str = "",
    size: str = "",
    worksheet=None,
) -> dict:
    """Update ONE price cell by generic name (Col A) or store keyword (Col I/J/K).

    Args:
        product_name: generic name to find in Col A (exact, case-insensitive,
            whitespace-normalized via KeywordIndex._normalize), falling back
            to the store's keyword col (Col I/J via STORE_KEYWORD_COL).
        store: "woolworths"|"coles".
        price: new price (float). Must be > 0.
        dry_run: if True, report old/new without writing.
        is_special: None = leave the specials cell untouched (P3a);
            True/False = write classify_special(...) to M/N (D25).
        special_desc: the live item's specials text (default "").
        size: Rule B resolved unit — written to a BLANK Col C in the same
            row write; a non-empty Col C is never modified (spec §5.3).
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
        # Step 2: match on this store's keyword col (Col I/J) via the
        # per-store keyword map (woolworths=8/coles=9). Fixes
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
    header = all_values[0] if all_values else []
    specials_col = _find_col(
        header, SPECIALS_HEADER_BY_STORE.get(store_lower, ""))
    write_specials = is_special is not None and specials_col is not None
    target_width = max(price_col + 1, LAST_UPDATED_COL + 1, SIZE_COL + 1)
    if write_specials:
        # Widen past M/N so the flag cell is inside the written range.
        target_width = max(target_width, specials_col + 1)
    while len(full_row) < target_width:
        full_row.append("")
    # Rule B/C.1: fill a BLANK Col C in the same row write (atomic,
    # no extra API call). Explicit size (marker allowed) wins;
    # otherwise parse from the matched name. Non-empty Col C is
    # NEVER modified (spec §5.3). Parse-based writes are real sizes
    # only — no marker is ever guessed here (D-U3).
    size_clean = str(size or "").strip()
    if not size_clean:
        m = _SIZE_PATTERN.search(product_name or "")
        size_clean = m.group(1).strip() if m else ""
    col_c = (str(full_row[SIZE_COL]).strip()
             if len(full_row) > SIZE_COL else "")
    if size_clean and not col_c:
        full_row[SIZE_COL] = size_clean
    full_row[price_col] = price
    full_row[LAST_UPDATED_COL] = ts
    if write_specials:
        from extractors.specials_parser import classify_special
        full_row[specials_col] = classify_special(is_special, special_desc)
    # Truncate to target_width — the sheet row has 16 cols (A-P); gspread
    # rejects writing past the range.
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
    exact Col A match first, then the store's keyword col (Col I/J).

    Args:
        product_name (str): Generic name (Col A) or store keyword to match.
        store (str): "woolworths" | "coles".
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


def mark_price_gone(
    product_name: str,
    store: str,
    worksheet=None,
    dry_run: bool = False,
) -> dict:
    """Write the manual GONE verdict into a store's price cell ONLY.

    User rule (2026-09-03): marking an item GONE must leave the store
    keyword (Col I/J) untouched and write the literal "GONE" into the
    store's price column (Col D/E). The GONE marker is exempt from
    marker writes during sync and is cleared only by a returning real
    price.

    Row matching reuses the same two-step strategy as update_single_price:
    exact Col A match first, then the store's keyword col (Col I/J).

    Args:
        product_name (str): Generic name (Col A) or store keyword to match.
        store (str): "woolworths" | "coles".
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

    # Live write: "GONE" into the price col ONLY. The keyword col is
    # deliberately left alone (user rule: GONE keeps the keyword).
    full_row = list(row_data)  # make mutable copy
    target_width = max(price_col + 1, 1)
    while len(full_row) < target_width:
        full_row.append("")
    full_row[price_col] = _GONE_MARKER
    # Truncate to target_width so the range write doesn't overflow into
    # columns past target_width (gspread rejects writing past the range).
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
    """Write a store keyword (Col I/J) for an existing sheet row.

    The user manually provides the exact store product name when live search
    returns nothing. This writes that name to the store's keyword column
    (Col I for woolworths, J for coles) so the row is matched on
    next sync.

    Args:
        product_name: Generic name (Col A) or existing keyword to match.
        store: "woolworths" | "coles".
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

# Store keyword column map (Col I/J) for add_product_row
STORE_KEYWORD_COL = {"woolworths": 8, "coles": 9}

# Keywords header for Col P (user-side aliases)
KEYWORDS_HEADER = "Keywords"


def _col_letter(idx: int) -> str:
    """0-based column index -> sheet letter ('A'->0, 'P'->15, 'AA'->26).

    Args:
        idx (int): 0-based column index.

    Returns:
        str: column letter(s).
    """
    letters = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _append_alias(worksheet, header: list, row_index: int, alias: str) -> str:
    """Append one alias to a row's Col P cell (pipe-delimited, deduped).

    Args:
        worksheet: connected gspread-like worksheet (needs
            get_all_values + update(values=..., range_name=...)).
        header (list): header row (to locate the Keywords column).
        row_index (int): 1-based sheet row number.
        alias (str): alias to append (skipped when already present).

    Returns:
        str: range written ("" when nothing needed writing).
    """
    from core.lookup import ALIAS_DELIM

    col = _find_col(header, KEYWORDS_HEADER)
    if col is None or not alias.strip():
        return ""
    values = worksheet.get_all_values()
    if row_index > len(values):   # row_index is 1-based (header = row 1)
        return ""
    row = values[row_index - 1]
    if len(row) <= col:
        row = row + [""] * (col + 1 - len(row))
    cell = str(row[col] or "").strip()
    aliases = [a.strip() for a in cell.split(ALIAS_DELIM) if a.strip()]
    alias_clean = alias.strip()
    if any(KeywordIndex._normalize(a) == KeywordIndex._normalize(alias_clean)
           for a in aliases):
        return ""  # already saved
    aliases.append(alias_clean)
    new_cell = ALIAS_DELIM.join(aliases)
    range_name = f"{_col_letter(col)}{row_index}:{_col_letter(col)}{row_index}"
    _update_with_backoff(
        worksheet, [[new_cell]], range_name)
    return range_name


def add_product_row(
    generic_name: str,
    store: str,
    price: float,
    *,
    brand: str = "",
    size: str,
    category: str = "",
    store_keyword: str = "",
    alias: str = "",
    is_special: bool = False,
    special_desc: str = "",
    dry_run: bool = False,
    allow_duplicate: bool = False,
    worksheet=None,
) -> dict:
    """Append a new product row to the bottom of Products_Master.

    Used by the lookup engine Step 5 auto-add: when a live search result
    is confirmed by the user, a new row is written with the generic name,
    the store's price (Col D/E), brand (Col G), timestamp (Col H), the
    store keyword (Col I/J), and optionally the user query as a Col P
    alias.

    ONE-LINE RULE (2026-09-02): before appending, the exact Col A guard
    and a similarity check run. When a near-identical product row exists
    (token-set ratio >= name_matcher.DUP_SIMILARITY_THRESHOLD) the add
    MERGES into it — the price is updated on that row and the alias is
    appended to its Col P — and NO second row is created. Pass
    allow_duplicate=True only when the user explicitly says the items
    are two different products (exact same names are still refused).

    Args:
        generic_name: the product name for Col A.
        store: "woolworths"|"coles" — which price column to fill.
        price: numeric price (must be > 0).
        brand: brand string for Col G (default "").
        size: REQUIRED Col C value — a real size ("1L") or the
            canonical marker "unit unavailable" (Rule B, spec B1).
        category: category string for Col B (default "").
        store_keyword: the store's exact product name for Col I/J
            (default "" — leave the keyword cell empty).
        alias: the user's original query to persist as a Col P alias
            (default "" — no alias written).
        is_special: the live item's specials flag (D25; default False).
        special_desc: the live item's specials text (D25).
        dry_run: if True, report the planned row without writing.
        allow_duplicate: skip the SIMILARITY merge (explicit
            "these are 2 different products" override). Exact-name
            duplicates are always refused.
        worksheet: optional pre-connected worksheet.

    Returns:
        dict with keys: wrote, merged (True when folded into an
        existing row), row_index, existing_name, range_written, error.
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
    size_clean = str(size or "").strip()
    if not size_clean:
        return {
            "wrote": False, "row_index": None, "range_written": "",
            "error": "unit is required: pass a size or the marker",
        }

    # --- connect & read ---
    if worksheet is None:
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    header = all_values[0] if all_values else []
    data_rows = all_values[1:] if len(all_values) > 1 else []

    # --- duplicate guard (2026-09-01 incident) ---
    # An explicit add for a name that already exists in Col A would
    # append a duplicate row (e.g. milk added while already tracked).
    # Refuse and point at the existing row — update/map handle those.
    new_norm = KeywordIndex._normalize(generic_name)
    if new_norm:
        for row_index, row in enumerate(data_rows, start=2):
            existing = row[0].strip() if row else ""
            if existing and KeywordIndex._normalize(existing) == new_norm:
                return {
                    "wrote": False,
                    "merged": False,
                    "row_index": row_index,
                    "existing_name": existing,
                    "range_written": "",
                    "error": (
                        f"already tracked (row {row_index}: "
                        f"'{existing}') — use update/map instead of "
                        f"adding a duplicate"),
                }

    # --- one-line rule (2026-09-02) ---
    # Same product = ONE row even when the stores name it differently
    # (word order, brand prefix, "5 pack" vs "70g"). Only a DIFFERENT
    # AMOUNT OF THE SAME UNIT (200g vs 400g, 1L vs 2L) keeps lines
    # apart — see name_matcher.is_same_product. allow_duplicate is the
    # explicit user override for genuinely different products.
    if not allow_duplicate:
        from core.name_matcher import is_same_product
        similar_idx: Optional[int] = None
        similar_name = ""
        for row_index, row in enumerate(data_rows, start=2):
            existing = row[0].strip() if row else ""
            if not existing:
                continue
            if is_same_product(generic_name, existing):
                similar_idx = row_index
                similar_name = existing
                break
        if similar_idx is not None:
            merged = update_single_price(
                similar_name, store_lower, price,
                is_special=is_special if is_special else None,
                special_desc=special_desc,
                size=size, worksheet=worksheet)
            range_written = str(merged.get("range_written", ""))
            if alias:
                range_written += _append_alias(
                    worksheet, header, similar_idx, alias)
            # 2026-09-03 gap fix: tell the caller whether the merged
            # row is still MISSING this store's keyword — the price
            # landed but the keyword loop needs a to-do entry.
            kw_col = STORE_KEYWORD_COL.get(store_lower)
            similar_row = data_rows[similar_idx - 2]
            kw_empty = (
                not str(similar_row[kw_col]).strip()
                if (kw_col is not None and len(similar_row) > kw_col)
                else True)
            return {
                "wrote": bool(merged.get("wrote")),
                "merged": True,
                "row_index": similar_idx,
                "existing_name": similar_name,
                "store_keyword_empty": kw_empty,
                "range_written": range_written,
                "error": merged.get("error", ""),
            }

    new_row_index = len(data_rows) + 2  # 1-based (row 1 = header)
    price_col = PRICE_COL[store_lower]
    kw_col = STORE_KEYWORD_COL.get(store_lower)
    keywords_col = _find_col(header, KEYWORDS_HEADER)
    specials_col = _find_col(
        header, SPECIALS_HEADER_BY_STORE.get(store_lower, ""))

    # Build the new row
    target_width = max(
        price_col + 1,
        LAST_UPDATED_COL + 1,
        (kw_col + 1) if kw_col is not None else 0,
        (keywords_col + 1) if keywords_col is not None else 0,
        (specials_col + 1) if specials_col is not None else 0,
        len(header),
    )
    new_row: list = [""] * target_width
    new_row[0] = generic_name.strip()             # Col A
    if category:
        new_row[1] = category                      # Col B
    new_row[SIZE_COL] = size_clean                 # Col C (always set)
    new_row[price_col] = price                     # Col D/E
    # Home-brand rows are classified ONCE at insert time: the literal
    # "Home" marker replaces the raw brand so every later discount calc
    # can trust Col G. Price cells ALWAYS stay raw (display-time only).
    from core.woolworths_discounts import is_woolworths_home_brand
    if is_woolworths_home_brand(generic_name, brand):
        new_row[6] = "Home"                        # Col G (marker)
    else:
        new_row[6] = brand                         # Col G
    new_row[LAST_UPDATED_COL] = _sydney_now_str()  # Col H
    if kw_col is not None and store_keyword:
        new_row[kw_col] = store_keyword            # Col I/J
    if keywords_col is not None and alias:
        new_row[keywords_col] = alias              # Col P
    if specials_col is not None:
        from extractors.specials_parser import classify_special
        new_row[specials_col] = classify_special(is_special, special_desc)

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
# Section F2: Row deletion (dead-row auto-cleanup, 2026-09-03)
# ============================================================================

def delete_product_rows(row_indices, worksheet=None, dry_run=False) -> dict:
    """Delete sheet rows by 1-based index, bottom-up (indices stay valid).

    Used by the Wednesday auto-delete (two-strike dead rows) and the
    manual `missed-pricing --purge`. Bottom-up ordering means earlier
    deletions never shift the indices of rows still to delete.

    Args:
        row_indices (list[int]): 1-based sheet row numbers (header = 1).
        worksheet: optional pre-connected gspread Worksheet.
        dry_run (bool): print the plan, delete nothing.

    Returns:
        dict: {"deleted": [...], "count": int, "dry_run": bool} where
        deleted is the sorted list of row indices removed (or planned).
    """
    targets = sorted({int(r) for r in row_indices if int(r) >= 2})
    if dry_run:
        if targets:
            print(f"[DRY RUN] delete_product_rows: would delete rows "
                  f"{targets}")
        return {"deleted": targets, "count": 0, "dry_run": True}

    if worksheet is None:
        worksheet = connect_worksheet()
    done = []
    for row_index in reversed(targets):  # bottom-up keeps indices valid
        worksheet.delete_rows(row_index)
        done.append(row_index)
    return {"deleted": sorted(done), "count": len(done), "dry_run": False}


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
