#!/usr/bin/env python3
"""Idempotent column audit + upgrade for Products_Master worksheet.

Adds Woolworths_Specials (M), Coles_Specials (N), Rewards_Points (O)
when they are absent. Also appends Sub_Category (Q), Item_Code (R),
Preferred (S). Safe to run multiple times.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

# Bootstrap
_HERE = Path(__file__).resolve().parent  # core/
_PROJECT = _HERE.parent  # grocery-price-tracker/
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from gspread.exceptions import APIError

from core.sheets_client import connect_worksheet

# ---------- constants ----------

EXPECTED_BASE_HEADERS = [
    "Product_Name", "Category", "Size", "Woolworths_Price", "Coles_Price",
    "Brand_Type", "Last_Updated", "Search_Keyword_Woolworths",
    "Search_Keyword_Coles",
]

NEW_COLUMNS = [
    "Woolworths_Specials",  # Col M
    "Coles_Specials",       # Col N
    "Rewards_Points",       # Col O
    "Keywords",             # Col P — user-side aliases (Phase 9.2)
    "Sub_Category",         # Col Q — granular cluster (spec §3)
    "Item_Code",            # Col R — permanent 3-letter row ID
    "Preferred",            # Col S — "P" flag, one per sub-category
]


def _normalize_header(s: str) -> str:
    """Lowercase, trim, collapse whitespace — for header comparison.
    Underscores are treated as whitespace to allow lenient matching."""
    normalized = str(s).strip().lower()
    normalized = normalized.replace("_", " ")
    return re.sub(r"\s+", " ", normalized)


# ---------- audit ----------


def audit_schema(worksheet=None) -> dict:
    """Read Products_Master headers and report missing columns.

    Returns dict:
        current_headers: list[str]            # as-is from row 1
        normalized_headers: list[str]          # lowercased for comparison
        missing_base: list[str]               # EXPECTED_BASE_HEADERS absent
        missing_new: list[str]                # NEW_COLUMNS absent
        existing_new: list[str]               # NEW_COLUMNS already present
        col_count: int
        needs_upgrade: bool                   # True if missing_new non-empty
    Connects via sheets_client if worksheet is None.
    Read-only. Never raises on a missing column; reports it.
    """
    if worksheet is None:
        worksheet = connect_worksheet()
    all_values = worksheet.get_all_values()
    current_headers = all_values[0] if all_values else []
    normalized_headers = [_normalize_header(h) for h in current_headers]

    missing_base = [
        h for h in EXPECTED_BASE_HEADERS
        if _normalize_header(h) not in normalized_headers
    ]
    missing_new = [
        h for h in NEW_COLUMNS
        if _normalize_header(h) not in normalized_headers
    ]
    existing_new = [
        h for h in NEW_COLUMNS
        if _normalize_header(h) in normalized_headers
    ]

    return {
        "current_headers": current_headers,
        "normalized_headers": normalized_headers,
        "missing_base": missing_base,
        "missing_new": missing_new,
        "existing_new": existing_new,
        "col_count": len(current_headers),
        "needs_upgrade": bool(missing_new),
    }


# ---------- upgrade ----------


def upgrade_schema(worksheet=None, *, dry_run: bool = False) -> dict:
    """Append missing NEW_COLUMNS to Products_Master. Idempotent.

    Behavior:
        1. audit = audit_schema(worksheet).
        2. If missing_new is empty: return with wrote=False, reason="up to date".
        3. If dry_run: return with wrote=False, planned_columns=missing_new.
        4. Else: add_cols, write header cells in one update, return report.

    Idempotency: re-running never duplicates columns.
    Never prints secrets.
    """
    report = audit_schema(worksheet)
    missing = report["missing_new"]  # preserves NEW_COLUMNS order

    if not missing:
        return {
            "wrote": False,
            "reason": "up to date",
            "added_columns": [],
            "dry_run": dry_run,
        }

    if dry_run:
        return {
            "wrote": False,
            "planned_columns": missing,
            "dry_run": True,
        }

    # Live upgrade
    ws = worksheet if worksheet is not None else connect_worksheet()
    start_col = report["col_count"] + 1  # 1-based column index
    ws.add_cols(len(missing))

    start_letter = _col_letter(start_col - 1)
    end_letter = _col_letter(start_col + len(missing) - 2)
    range_name = f"{start_letter}1:{end_letter}1"
    _update_with_backoff(ws, [missing], range_name)

    return {
        "wrote": True,
        "added_columns": missing,
        "start_col": start_col,
        "range": range_name,
        "dry_run": False,
    }


# ---------- helpers ----------


def _col_letter(idx: int) -> str:
    """0-based index -> spreadsheet column letter (0->A, 25->Z, 26->AA)."""
    if idx < 26:
        return chr(65 + idx)
    return _col_letter(idx // 26 - 1) + _col_letter(idx % 26)


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


# ---------- CLI ----------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Idempotent schema upgrade for Products_Master"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Audit and report missing columns without writing",
    )
    args = parser.parse_args()

    try:
        result = upgrade_schema(dry_run=args.dry_run)
        import json
        print(json.dumps(result, indent=2))
        sys.exit(0)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
