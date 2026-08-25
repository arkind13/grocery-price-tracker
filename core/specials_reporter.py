#!/usr/bin/env python3
"""Active specials & bonus rewards reporter from the synced Products_Master.

Reads columns M (Woolworths_Specials), N (Coles_Specials), O (Rewards_Points)
via ONE get_all_values() call. Read-only — never writes to the sheet.
"""
from __future__ import annotations
import argparse
import re
import sys
from typing import Optional

from core.sheets_sync import _find_col, PRICE_COL


# ============================================================================
# Section B: get_active_specials()
# ============================================================================


def get_active_specials(store=None, worksheet=None) -> list:
    """Return products currently on special from the synced sheet.

    Args:
        store: "woolworths"|"coles"|None. If None, both stores.
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        list[dict], each: {name, store, special_desc, price, row_index}.
        A product is "on special" if its store specials cell (M for
        woolworths, N for coles) is non-empty.
    """
    store_lower = store.lower() if store else None

    # Connect if needed
    if worksheet is None:
        from core.sheets_client import connect_worksheet
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    if not all_values or len(all_values) < 2:
        return []

    header = all_values[0]
    rows = all_values[1:]

    # Resolve specials columns by header name
    specials_col = {}
    for store_key in ("woolworths", "coles"):
        if store_lower and store_lower != store_key:
            continue
        header_name = f"{store_key.capitalize()}_Specials"
        idx = _find_col(header, header_name)
        if idx is not None:
            specials_col[store_key] = idx
        else:
            print(
                f"[specials_reporter] {header_name} column absent",
                file=sys.stderr,
            )

    if not specials_col:
        return []

    results = []
    for row_idx, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        name = str(row[0]).strip()
        sheet_row = row_idx + 2  # 1-based

        for store_key, col_idx in specials_col.items():
            if col_idx < len(row) and row[col_idx].strip():
                # Parse price
                price = None
                price_col = PRICE_COL.get(store_key)
                if price_col is not None and price_col < len(row):
                    cell = str(row[price_col])
                    m = re.search(r"(?:A\$|\$)\s*(\d+\.?\d*)", cell)
                    if m:
                        price = float(m.group(1))
                    else:
                        try:
                            price = float(cell)
                        except (ValueError, TypeError):
                            pass
                results.append({
                    "name": name,
                    "store": store_key,
                    "special_desc": str(row[col_idx]).strip(),
                    "price": price,
                    "row_index": sheet_row,
                })

    return results


# ============================================================================
# Section C: get_bonus_rewards()
# ============================================================================


def get_bonus_rewards(store=None, worksheet=None) -> list:
    """Return products offering bonus rewards points (col O non-empty).

    Args:
        store: filter hint. If set, only return rows whose rewards string
            contains the store name (case-insensitive); else all.
        worksheet: optional pre-connected worksheet.

    Returns:
        list[dict], each: {name, rewards, price, row_index}.
    """
    if worksheet is None:
        from core.sheets_client import connect_worksheet
        worksheet = connect_worksheet()

    all_values = worksheet.get_all_values()
    if not all_values or len(all_values) < 2:
        return []

    header = all_values[0]
    rows = all_values[1:]

    rewards_col = _find_col(header, "Rewards_Points")
    if rewards_col is None:
        print(
            "[specials_reporter] Rewards_Points column absent",
            file=sys.stderr,
        )
        return []

    store_lower = store.lower() if store else None

    results = []
    for row_idx, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        name = str(row[0]).strip()
        sheet_row = row_idx + 2

        if rewards_col < len(row) and row[rewards_col].strip():
            rewards_text = str(row[rewards_col]).strip()

            # Filter by store if requested
            if store_lower and store_lower not in rewards_text.lower():
                continue

            # Parse price (any store, first available)
            price = None
            for store_key, price_col in PRICE_COL.items():
                if price_col < len(row) and row[price_col]:
                    cell = str(row[price_col])
                    m = re.search(r"(?:A\$|\$)\s*(\d+\.?\d*)", cell)
                    if m:
                        price = float(m.group(1))
                        break
                    try:
                        price = float(cell)
                        break
                    except (ValueError, TypeError):
                        pass

            results.append({
                "name": name,
                "rewards": rewards_text,
                "price": price,
                "row_index": sheet_row,
            })

    return results


# ============================================================================
# Section D: format_specials_report()
# ============================================================================


def format_specials_report(specials: list, store=None) -> str:
    """Render a Markdown table: item name, store, special_desc, price.
    Top 25 rows + a count summary. Secret-free.
    """
    if not specials:
        return "No active specials."

    store_label = store.capitalize() if store else "All Stores"
    lines = [
        f"**Active Specials — {store_label}**",
        "",
        "| # | Product | Store | Special | Price |",
        "|---|---------|-------|---------|-------|",
    ]

    for i, s in enumerate(specials[:25], 1):
        price_str = (
            f"${s['price']:.2f}" if s.get("price") is not None else "—"
        )
        lines.append(
            f"| {i} | {s['name']} | {s['store'].capitalize()} | "
            f"{s['special_desc']} | {price_str} |"
        )

    if len(specials) > 25:
        lines.append(
            f"| ... | *{len(specials) - 25} more specials* | | | |"
        )

    lines.append("")
    lines.append(f"**Total:** {len(specials)} active special(s)")
    return "\n".join(lines)


# ============================================================================
# Section E: __main__
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Report active specials and bonus rewards"
    )
    parser.add_argument(
        "--store", default="all",
        choices=["woolworths", "coles", "all"],
        help="Filter by store (default: all)"
    )
    args = parser.parse_args()

    try:
        store = None if args.store == "all" else args.store
        specials = get_active_specials(store=store)
        print(format_specials_report(specials, store))
        print()

        rewards = get_bonus_rewards(store=store)
        if rewards:
            print("**Bonus Rewards:**")
            for r in rewards:
                print(f"  - {r['name']}: {r['rewards']}")
            print(f"  Total: {len(rewards)} bonus reward(s)")
        else:
            print("No bonus rewards.")
        sys.exit(0)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
