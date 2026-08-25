#!/usr/bin/env python3
"""Shared specials-marker parsing for Woolworths saved lists.

Centralises the dual-logic (SAVE forward-look / multi-buy backward-look)
special detection so both the sheet-sync path (``doc_parser.parse_docx``)
and the Telegram-report path (``grocery_price_cli._extract_woolworths_specials``)
use one implementation.

Recognised markers (on the line directly below the current price):
  * ``SAVE $X.XX`` — dollar-off special. Discount % is computed as
    ``save / (price + save) * 100`` relative to the original price.
  * ``N FOR $XXX`` — multi-buy bundle special (e.g. ``2 for $4.50``).

The Woolworths saved-list layout is three lines per special::

    <Product Name>
    $<current price>
    <detail line: "save $1.53" or "2 for $4.50">
"""
from __future__ import annotations

import re
from typing import Optional

# SAVE marker uses a non-breaking space (\xa0) in the saved-list layout:
# ``SAVE\xa0$1.53``.
SAVE_RE = re.compile(
    r"save[\s\xa0]+\$?\s*([\d]+(?:\.[\d]{1,2})?)", re.IGNORECASE
)

# Multi-buy bundle: ``2 for $4.50``. Requires a leading quantity digit so
# product names like "Cream For Men" are not false-matched.
FOR_RE = re.compile(
    r"(\d+)\s*for\s+\$?\s*([\d]+(?:\.[\d]{1,2})?)", re.IGNORECASE
)

# A *clean* price line is a bare amount like ``$1.52`` (matched start to
# end) — unit-price lines such as ``$10.00 / 1KG`` are rejected by also
# checking the line has no ``/``.
CLEAN_PRICE_RE = re.compile(r"^\$?\s*(\d+(?:\.\d{1,2})?)$")


def find_name_price_after(
    lines: list[str], start: int, end: int
) -> tuple[Optional[str], Optional[float]]:
    """Return (name, price) for the next name->clean-price pair after
    ``start``. Used for SAVE markers, which appear BEFORE the product.

    Args:
        lines: list of stripped paragraph strings (non-empty only).
        start: index to begin scanning forward from (inclusive).
        end: exclusive upper bound (clamped to len(lines)).

    Returns:
        (name, price) or (None, None) if no pair found.
    """
    for j in range(start, min(end, len(lines))):
        cand = lines[j]
        if "$" in cand or len(cand) <= 3:
            continue
        for k in range(j + 1, min(j + 4, len(lines))):
            pm = CLEAN_PRICE_RE.match(lines[k].strip())
            if pm and "/" not in lines[k]:
                return cand, float(pm.group(1))
    return None, None


def find_name_price_before(
    lines: list[str], start: int, end: int
) -> tuple[Optional[str], Optional[float]]:
    """Return (name, price) for the clean-price->name pair before
    ``start``. Used for FOR markers, which appear AFTER the product.

    Args:
        lines: list of stripped paragraph strings (non-empty only).
        start: index to begin scanning backward from (inclusive).
        end: exclusive lower bound (may be negative; clamped to -1).

    Returns:
        (name, price) or (None, None) if no pair found.
    """
    for j in range(start, max(end, -1), -1):
        cand = lines[j].strip()
        pm = CLEAN_PRICE_RE.match(cand)
        if pm and "/" not in cand:
            price = float(pm.group(1))
            for k in range(j - 1, max(j - 5, -1), -1):
                name_cand = lines[k]
                if "$" in name_cand or len(name_cand) <= 3:
                    continue
                return name_cand, price
    return None, None


def detect_special(
    lines: list[str], idx: int
) -> tuple[Optional[str], Optional[float], Optional[str], Optional[float]]:
    """Detect a specials marker on line ``idx`` and resolve its product.

    Checks ``lines[idx]`` for a SAVE or multi-buy FOR marker, then looks
    forward (SAVE) or backward (FOR) to find the associated name+price pair.

    Args:
        lines: list of stripped paragraph strings (non-empty only).
        idx: index of the line to scan for a marker.

    Returns:
        ``(name, price, detail, discount_pct)`` where:
          * ``name``: product name (str) or None if no marker found.
          * ``price``: current price (float) or None.
          * ``detail``: human-readable special text (e.g.
            ``"save $1.53 (35% off)"`` / ``"2 for $4.50"``) or None.
          * ``discount_pct``: float for save specials, None for multi-buy.
    """
    line = lines[idx]
    save_m = SAVE_RE.search(line)
    for_m = FOR_RE.search(line)

    name = None
    price = None
    detail = None
    discount_pct = None

    if save_m:
        # SAVE marker appears BEFORE the product name+price.
        name, price = find_name_price_after(lines, idx + 1, idx + 7)
        if name and price:
            save_amt = float(save_m.group(1))
            original = price + save_amt
            discount_pct = (
                (save_amt / original * 100.0) if original > 0 else 0.0
            )
            detail = f"save ${save_amt:.2f} ({discount_pct:.0f}% off)"
    elif for_m:
        # FOR marker appears AFTER the product name+price.
        name, price = find_name_price_before(lines, idx - 1, idx - 7)
        if name and price:
            qty = int(for_m.group(1))
            bundle = float(for_m.group(2))
            detail = f"{qty} for ${bundle:.2f}"

    return name, price, detail, discount_pct
