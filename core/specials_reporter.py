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


def _resolve_brand_col(header) -> int:
    """Resolve the brand column index for a Products_Master header.

    Prefers a column titled "Brand", then "Brand_Type"; falls back to
    positional Col G (index 6) which is the historical brand cell.

    Args:
        header: first spreadsheet row (list of title strings).

    Returns:
        0-based column index.
    """
    col = _find_col(header, "Brand")
    if col is None:
        col = _find_col(header, "Brand_Type")
    return 6 if col is None else col


# ============================================================================
# Section B: get_active_specials()
# ============================================================================


def get_active_specials(store=None, worksheet=None) -> list:
    """Return products currently on special from the synced sheet.

    Args:
        store: "woolworths"|"coles"|None. If None, both stores.
        worksheet: optional pre-connected worksheet for tests.

    Returns:
        list[dict], each: {name, store, special_desc, price, brand,
        row_index}. A product is "on special" if its store specials cell
        (M for woolworths, N for coles) is non-empty and not "no" (D25/A6).
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

    brand_col = _resolve_brand_col(header)

    results = []
    for row_idx, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        name = str(row[0]).strip()
        brand = (
            str(row[brand_col]).strip()
            if brand_col < len(row) else ""
        )
        sheet_row = row_idx + 2  # 1-based

        for store_key, col_idx in specials_col.items():
            if col_idx >= len(row):
                continue
            cell = str(row[col_idx]).strip()
            # A6 back-compat: empty/"no" -> not on special; "multi-buy"
            # reports as multi-buy; ANY other non-empty cell (incl.
            # legacy free text) reports as a special (discount).
            if not cell or cell.lower() == "no":
                continue
            # Parse price
            price = None
            price_col = PRICE_COL.get(store_key)
            if price_col is not None and price_col < len(row):
                pcell = str(row[price_col])
                m = re.search(r"(?:A\$|\$)\s*(\d+\.?\d*)", pcell)
                if m:
                    price = float(m.group(1))
                else:
                    try:
                        price = float(pcell)
                    except (ValueError, TypeError):
                        pass
            results.append({
                "name": name,
                "store": store_key,
                "special_desc": cell,
                "price": price,
                "brand": brand,
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
        list[dict], each: {name, rewards, price, store, brand,
        row_index}. "store" records WHICH store's price column supplied
        the parsed price ("" when none parsed).
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
    brand_col = _resolve_brand_col(header)

    results = []
    for row_idx, row in enumerate(rows):
        if not row or not row[0].strip():
            continue
        name = str(row[0]).strip()
        brand = (
            str(row[brand_col]).strip()
            if brand_col < len(row) else ""
        )
        sheet_row = row_idx + 2

        if rewards_col < len(row) and row[rewards_col].strip():
            rewards_text = str(row[rewards_col]).strip()

            # Filter by store if requested
            if store_lower and store_lower not in rewards_text.lower():
                continue

            # Parse price (any store, first available) — remember which
            # store's column supplied it so discounts can be attributed.
            price = None
            price_store = ""
            for store_key, price_col in PRICE_COL.items():
                if price_col < len(row) and row[price_col]:
                    cell = str(row[price_col])
                    m = re.search(r"(?:A\$|\$)\s*(\d+\.?\d*)", cell)
                    if m:
                        price = float(m.group(1))
                        price_store = store_key
                        break
                    try:
                        price = float(cell)
                        price_store = store_key
                        break
                    except (ValueError, TypeError):
                        pass

            results.append({
                "name": name,
                "rewards": rewards_text,
                "price": price,
                "store": price_store,
                "brand": brand,
                "row_index": sheet_row,
            })

    return results


# ============================================================================
# Section D: format_specials_report()
# ============================================================================


def format_specials_report(specials: list, store=None) -> str:
    """Render the Telegram-style specials report (spec §5.3).

    List-style numbered items: the price line shows the always-on
    discounted price for Woolworths rows (extra 5% when the row's
    brand/name is a home brand); Coles rows stay raw. The special
    description rides along via a `·` separator. No "(was $x)" suffix
    is invented for the team discount — genuine "Was $x" specials text
    from the sheet shows through the description. Top 25 rows + an
    overflow line + a 📊 count line. Pipe-free (no markdown tables).
    Secret-free.
    """
    if not specials:
        return "No active specials."

    from core.telegram_format import header
    from core.woolworths_discounts import (
        format_discounted_price,
        is_woolworths_home_brand,
    )

    store_label = store.capitalize() if store else "All Stores"
    lines = [header(f"Specials — {store_label}", "🏷️"), ""]

    for i, s in enumerate(specials[:25], 1):
        raw_price = s.get("price")
        if s.get("store") == "woolworths" and raw_price is not None:
            price_str = format_discounted_price(
                raw_price,
                is_woolworths_home_brand(
                    s.get("name", ""), s.get("brand", "")
                ),
            )
        else:
            price_str = (
                f"${raw_price:.2f}" if raw_price is not None else "—"
            )
        price_line = f"   {price_str}"
        desc = (s.get("special_desc") or "").strip()
        if desc:
            price_line += f"  ·  {desc}"
        lines.append(f"{i}. {s['name']}")
        lines.append(price_line)

    if len(specials) > 25:
        lines.append(f"… +{len(specials) - 25} more specials")

    lines.append("")
    lines.append(f"📊 {len(specials)} active specials")
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
            from core.telegram_format import subheader, ok
            print(subheader("BONUS REWARDS", "💰"))
            for r in rewards:
                print(ok(f"{r['name']} · {r['rewards']}"))
            print(f"📊 {len(rewards)} bonus rewards")
        else:
            print("No bonus rewards.")
        sys.exit(0)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
