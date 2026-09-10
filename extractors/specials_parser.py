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

import os
import re
import sys
from typing import Optional

from extractors.models import ProductItem

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

# D25 Coles markers:
#   ``Was $X`` — dollar-off special (same style as SAVE_RE).
WAS_RE = re.compile(
    r"was[\s\xa0]+\$?\s*([\d]+(?:\.[\d]{1,2})?)", re.IGNORECASE
)

#   ``Any N | $X`` — multi-buy (e.g. ``Any 2 | $9``); spacing/case tolerant.
ANY_RE = re.compile(
    r"any\s+(\d+)\s*\|\s*\$?\s*([\d]+(?:\.[\d]{1,2})?)", re.IGNORECASE
)

#   Bare ``SPECIAL`` flag line (Coles layout places it ABOVE the name).
#   Surrounding whitespace tolerated (the doc_parser call site strips
#   too; a line must contain ONLY the word to count).
SPECIAL_FLAG_RE = re.compile(r"^\s*special\s*$", re.IGNORECASE)

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


def classify_special(is_special: bool, special_desc: str) -> str:
    """Classify a specials observation into the D25 sheet vocabulary.

    Precedence (decision 25, binding):
        1. ``Any N | $X`` (or ``N for $X``) in desc -> "multi-buy";
        2. Save/Was in desc, or ``is_special`` flag -> "discount";
        3. otherwise -> "no".

    Args:
        is_special: the item's specials flag (docx marker or live API).
        special_desc: the item's specials text ("" when none).

    Returns:
        str: exactly one of "multi-buy" | "discount" | "no".
    """
    desc = special_desc or ""
    if ANY_RE.search(desc) or FOR_RE.search(desc):
        return "multi-buy"
    if WAS_RE.search(desc) or SAVE_RE.search(desc) or is_special:
        return "discount"
    return "no"


# ============================================================================
# Section D: the saved "Special list" panel docx (2026-09-10 user fix)
# ============================================================================
#
# The saved specials PAGE renders one panel per product, and out-of-stock
# panels carry NO price line at all — doc_parser.parse_docx's strict
# name->price adjacency drops those items (8 of the user's 33) and never
# sees SAVE badges that render above the name or below the cart buttons.
# This walker parses the panel structure directly.

_NAME_SIZE_RE = re.compile(
    r"\d+\s?(?:g|kg|mL|L|pack|pk|pks|pc|pcs)\b", re.IGNORECASE
)
_PRICE_ONLY_RE = re.compile(r"^\$?\d+(?:\.\d{1,2})?$")
_BADGE_HINT_RE = re.compile(
    r"(save|\bfor\s*\$|was\s*\$|any\s+\d+\s*\||bonus)", re.IGNORECASE
)
_ANY_NUMBER_WORDS = ("quantity", "toggle", "cart", "dropdown")


def _is_specials_name_line(text: str, ignore_fn) -> bool:
    """A product-name line: carries a size token, no '$', not page
    furniture (doc_parser's ignore list + the panel's own controls)."""
    t = text.strip()
    if not t or "$" in t or len(t) < 7:
        return False
    if not _NAME_SIZE_RE.search(t):
        return False
    low = t.lower()
    if any(word in low for word in _ANY_NUMBER_WORDS):
        return False
    return not ignore_fn(t)


def _clean_ws(text: str) -> str:
    """Collapse \xa0 and repeated whitespace to single spaces."""
    return " ".join(str(text).split())


def parse_specials_docx(file_path: str,
                        store: str = "woolworths") -> list:
    """Parse the saved Woolworths 'Special list' panel docx.

    Segment the page into product blocks by NAME lines, take each
    block's first pure price line (out-of-stock panels have none ->
    price None), and attribute badge lines (SAVE / N for / Was /
    Any N | $X / bonus):

    1. a badge directly after a block's NAME line -> that item
       (the Essano case: out-of-stock, badge under the name);
    2. else a badge followed by the NEXT block's name -> that item
       (the panel-boundary cases: badge renders above the following
       product's name — Weet-Bix / Air Wick);
    3. else -> the surrounding block's item (2-for / bonus below the
       unit-price line — Eclipse / Farmers Union).

    Every parsed item is returned in page order with ``is_special``
    set from its badges (the document IS the saved specials list; the
    Telegram report shows all items either way).
    """
    try:
        from docx import Document
    except ImportError:
        print(
            "[specials_parser] python-docx not installed. "
            "Install with: pip install python-docx",
            file=sys.stderr,
        )
        return []

    from extractors.doc_parser import (
        _detect_brand, _detect_category, _extract_size, _is_ignore_line,
    )

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    doc = Document(file_path)
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    name_idx = [i for i, ln in enumerate(lines)
                if _is_specials_name_line(ln, _is_ignore_line)]
    if not name_idx:
        return []

    # per-item badge lines (raw), keyed by block position
    item_badges: dict = {pos: [] for pos in range(len(name_idx))}
    for pos, i in enumerate(name_idx):
        end = name_idx[pos + 1] if pos + 1 < len(name_idx) else len(lines)
        block = lines[i + 1:end]
        for j, ln in enumerate(block):
            if _PRICE_ONLY_RE.match(ln) or not _BADGE_HINT_RE.search(ln):
                continue
            low = ln.lower()
            if ("you pay" in low or "you save" in low
                    or "save up to" in low):
                continue               # cost-summary furniture
            if not (SAVE_RE.search(ln) or FOR_RE.search(ln)
                    or WAS_RE.search(ln) or ANY_RE.search(ln)
                    or "bonus" in low):
                continue               # hint word without a real marker
            if j == 0 or _is_specials_name_line(block[j - 1],
                                                 _is_ignore_line):
                target = pos                       # (1) under our name
            else:
                nxt = block[j + 1] if j + 1 < len(block) else None
                if nxt is None or _is_specials_name_line(
                        nxt, _is_ignore_line):
                    target = pos + 1               # (2) next panel
                else:                              # (3) this panel
                    target = pos
            if target < len(name_idx):
                item_badges[target].append(_clean_ws(ln))

    items: list = []
    for pos, i in enumerate(name_idx):
        end = name_idx[pos + 1] if pos + 1 < len(name_idx) else len(lines)
        name = lines[i]
        price = None
        for ln in lines[i + 1:end]:
            if _PRICE_ONLY_RE.match(ln):
                price = float(ln.lstrip("$").replace(",", "."))
                break
        badges = item_badges.get(pos) or []
        descs: list = []
        for badge in badges:
            save_m = SAVE_RE.search(badge)
            for_m = FOR_RE.search(badge)
            if save_m:
                save_amt = float(save_m.group(1))
                if price:
                    original = price + save_amt
                    pct = (save_amt / original * 100.0) if original else 0
                    descs.append(f"save ${save_amt:.2f} ({pct:.0f}% off)")
                else:
                    descs.append(f"save ${save_amt:.2f}")
            elif for_m:
                descs.append(
                    f"{int(for_m.group(1))} for ${float(for_m.group(2)):.2f}")
            else:
                descs.append(badge)          # bonus / Was / Any kept as-is
        items.append(ProductItem(
            store=store,
            raw_name=name,
            price=price,
            category=_detect_category(name),
            size=_extract_size(name),
            brand=_detect_brand(name),
            is_special=bool(descs),
            special_desc=" + ".join(descs),
        ))
    return items
