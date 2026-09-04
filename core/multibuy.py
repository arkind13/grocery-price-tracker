#!/usr/bin/env python3
"""Multi-buy ("2 for $6.00") parsing, rates, display — spec §7.

Display + math ONLY; never touches core/uom.py (§7.3 rule 5).
Parsing REUSES extractors.specials_parser FOR_RE / ANY_RE (no regex
duplication, spec §12).

USER REVISION 2026-09-05 (overrides D-MB3): "Any N | $X" promos are
RATE-ELIGIBLE multi-buy deals — in-store they mean any N units from
the same range/brand, so the per-unit rate participates in sheet
prices and comparison math exactly like "N for $X" deals. There is
no informational-only promo class any more.
"""
from __future__ import annotations

import re

from extractors.specials_parser import ANY_RE, FOR_RE

MULTIBUY_PREFIX = "multi-buy"  # M/N cell vocabulary prefix (D25)

# Encoded cell-terms form "2/$6.00" (the suffix encode_multibuy_cell
# appends). parse_multibuy cannot read it — FOR_RE demands the word
# "for" — so decode tries the shared regexes first, then this.
_CELL_TERMS_RE = re.compile(
    r"(\d+)\s*/\s*\$\s*([\d]+(?:\.[\d]{1,2})?)"
)


def parse_multibuy(desc: str) -> tuple[int, float] | None:
    """Parse "2 for $6.00" / "Any 2 | $9" style promo text.

    Args:
        desc: specials text (docx line, live special_desc, M/N cell).

    Returns:
        (qty, bundle_total) with qty >= 2 and total > 0, else None.
    """
    text = str(desc or "")
    match = FOR_RE.search(text) or ANY_RE.search(text)
    if not match:
        return None
    qty = int(match.group(1))
    total = float(match.group(2))
    if qty < 2 or total <= 0:
        return None
    return (qty, total)


def effective_unit_rate(qty: int, total: float) -> float:
    """Bundle per-unit rate: total / qty (6.00 / 2 = 3.00).

    Raises:
        ValueError: qty < 2 or total <= 0.
    """
    if qty < 2 or total <= 0:
        raise ValueError("multi-buy needs qty >= 2 and total > 0")
    return round(total / qty, 2)


def encode_multibuy_cell(qty: int, total: float) -> str:
    """D25 prefix + parseable terms: "multi-buy 2/$6.00" (§7.2)."""
    return f"{MULTIBUY_PREFIX} {qty}/${total:.2f}"


def decode_multibuy_cell(cell: str) -> tuple[int, float] | None:
    """Decode an M/N cell into (qty, total).

    Accepts both the encoded "multi-buy 2/$6.00" form and FOR/ANY
    promo text after the prefix. Returns None for: empty cell,
    non-multi-buy cell, legacy bare "multi-buy" (no terms —
    informational only), unparsable terms.
    """
    text = str(cell or "").strip()
    if not text.lower().startswith(MULTIBUY_PREFIX):
        return None
    terms = parse_multibuy(text)
    if terms is not None:
        return terms
    match = _CELL_TERMS_RE.search(text)
    if not match:
        return None
    qty = int(match.group(1))
    total = float(match.group(2))
    if qty < 2 or total <= 0:
        return None
    return (qty, total)


def is_multibuy_cell(cell: str) -> bool:
    """True for ANY cell starting with the prefix (incl. bare legacy)."""
    return str(cell or "").strip().lower().startswith(MULTIBUY_PREFIX)


def format_multibuy_note(qty: int, total: float) -> str:
    """Mandatory display tag, EXACT text (§7.3 rule 2).

    Delegates to core.telegram_format.multibuy_tag so the note text
    has ONE source of truth (§12 telegram_format helper).
    """
    from core.telegram_format import multibuy_tag
    return multibuy_tag(qty, total)
