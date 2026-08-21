#!/usr/bin/env python3
"""Shared data models for supermarket product extraction.

Defines the ``ProductItem`` dataclass used across all extractors,
the hub, and downstream modules (sync, comparator, CLI).
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ProductItem:
    """Standardised representation of a single grocery product.

    All extractors (Woolworths, Coles, Aldi) return lists of this type.
    Fields not available from a given store are left as ``None``.

    Attributes:
        store: Store identifier (``"woolworths"``, ``"coles"``, ``"aldi"``).
        raw_name: Product name exactly as listed on the store website.
        price: Numeric price in AUD (float).
        is_special: Whether the product is on special / discounted.
        special_desc: Human-readable special description (e.g. ``"Save $2.00"``,
            ``"Buy 2 for $6"``). Empty string if not on special.
        rewards_points: Bonus rewards / flybuys points offered (int or str).
            ``0`` or ``""`` if none.
        unit_price: Per-unit price string (e.g. ``"$3.50 / 1L"``).
            Empty string if not available.
        category: Inferred product category (e.g. ``"Dairy"``, ``"Meat"``).
            Empty string if unknown.
        size: Product size string (e.g. ``"1L"``, ``"500g"``).
            Empty string if not available.
        brand: Product brand name. Empty string if unknown.
        timestamp: ISO-8601 timestamp of when this data was extracted.
    """

    store: str
    raw_name: str
    price: float
    is_special: bool = False
    special_desc: str = ""
    rewards_points: str = ""
    unit_price: str = ""
    category: str = ""
    size: str = ""
    brand: str = ""
    timestamp: str = field(default_factory=lambda: _now_iso())

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict of this item."""
        return asdict(self)

    def to_tuple(self) -> tuple:
        """Return a tuple matching the ``Products_Master`` column order.

        Columns: (Product_Name, Category, Size, Woolworths_Price,
        Coles_Price, Aldi_Price, Brand_Type, Last_Updated,
        Search_Keyword_Woolworths, Search_Keyword_Coles,
        Search_Keyword_Aldi, Aldi_Refresh)
        """
        return (
            self.raw_name,  # Product_Name
            self.category,  # Category
            self.size,      # Size
            "",             # Woolworths_Price (filled by sync)
            "",             # Coles_Price (filled by sync)
            "",             # Aldi_Price (filled by sync)
            self.brand,     # Brand_Type
            self.timestamp, # Last_Updated
            "",             # Search_Keyword_Woolworths (filled by matcher)
            "",             # Search_Keyword_Coles (filled by matcher)
            "",             # Search_Keyword_Aldi (filled by matcher)
            "",             # Aldi_Refresh
        )


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
