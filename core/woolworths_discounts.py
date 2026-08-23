#!/usr/bin/env python3
"""Woolworths discount engine: home-brand detection, Team Discount (5%),
monthly Extra Discount, and usage tracker."""
from __future__ import annotations
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

TEAM_DISCOUNT_RATE = 0.05  # 5% off home-brand Woolworths items

# Woolworths-owned home-brand labels (case-insensitive substring match).
HOME_BRAND_LABELS = (
    "woolworths", "macro", "the odd bunch", "gold", "free from",
)

# Monthly discount tracker (one use per calendar month).
TRACKER_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "woolworths_discount_usage.json"
)


# ============================================================================
# Section B: Home-brand detection
# ============================================================================


def is_woolworths_home_brand(product_name: str, brand: str) -> bool:
    """True if the product is a Woolworths home-brand item.

    Detection (case-insensitive substring on either field):
        - brand contains "woolworths", OR
        - product_name contains "woolworths", OR
        - brand or product_name contains any HOME_BRAND_LABELS
          ("macro", "the odd bunch", "gold", "free from").

    Args:
        product_name: raw or generic name (may be "").
        brand: Brand_Type / ProductItem.brand (may be "").

    Returns:
        bool. False if both inputs are empty/whitespace.
    """
    name_lower = product_name.lower() if product_name else ""
    brand_lower = brand.lower() if brand else ""
    if not name_lower and not brand_lower:
        return False
    combined = f"{name_lower} {brand_lower}"
    for label in HOME_BRAND_LABELS:
        if label in combined:
            return True
    return False


# ============================================================================
# Section C: Team Discount
# ============================================================================


def apply_team_discount(items, store: str = "woolworths") -> list:
    """Apply 5% Team Discount to home-brand Woolworths items.

    Args:
        items: iterable of dicts OR objects with .price, .brand, .raw_name.
            Accepts ProductItem directly (duck-typed attribute access).
        store: must be "woolworths" (only store with Team Discount).
            Any other store returns items unchanged with applied=False.

    Returns:
        list[dict] one per input item, each:
            {name, brand, original_price, discounted_price, applied: bool}
        discounted_price = original * 0.95 when applied, else original.
    """
    store_lower = store.lower()
    results = []
    for item in items:
        # Duck-typed access: try dict, then attribute
        if isinstance(item, dict):
            price = item.get("price", 0.0)
            brand = item.get("brand", "")
            name = item.get("name", item.get("raw_name", ""))
        else:
            price = getattr(item, "price", 0.0)
            brand = getattr(item, "brand", "")
            name = getattr(item, "raw_name", getattr(item, "name", ""))

        applied = False
        discounted = float(price)
        if store_lower == "woolworths" and is_woolworths_home_brand(name, brand):
            discounted = round(price * (1 - TEAM_DISCOUNT_RATE), 2)
            applied = True

        results.append({
            "name": name,
            "brand": brand,
            "original_price": float(price),
            "discounted_price": discounted,
            "applied": applied,
        })
    return results


# ============================================================================
# Section D: Extra Discount
# ============================================================================


def apply_extra_discount(basket_total: float, discount_pct: float) -> tuple:
    """Apply X% discount to a Woolworths basket total.

    Args:
        basket_total: the post-Team-Discount Woolworths total (>= 0).
        discount_pct: 0-100.

    Returns:
        (discounted_total, savings_amount) as floats.
        discounted_total = basket_total * (1 - pct/100).
        savings_amount = basket_total - discounted_total.
        Validates pct in [0,100] (clamp; never raise).
    """
    pct = max(0.0, min(100.0, float(discount_pct)))
    if pct == 0.0:
        return (basket_total, 0.0)
    discounted = round(basket_total * (1 - pct / 100.0), 2)
    savings = round(basket_total - discounted, 2)
    return (discounted, savings)


# ============================================================================
# Section E: Monthly usage tracker
# ============================================================================


def _current_month() -> str:
    """Return current month as YYYY-MM (Sydney time, fallback UTC)."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Australia/Sydney"))
    except Exception:
        now = datetime.utcnow()
    return now.strftime("%Y-%m")


def _current_iso() -> str:
    """Return current timestamp as ISO-8601 string."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Australia/Sydney"))
    except Exception:
        now = datetime.utcnow()
    return now.isoformat()


def _read_tracker() -> dict:
    """Read TRACKER_PATH. Return dict or empty dict on failure."""
    try:
        if TRACKER_PATH.exists():
            with open(TRACKER_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        print(
            f"[woolworths_discounts] tracker read failed: {exc}",
            file=sys.stderr,
        )
    return {}


def _write_tracker(data: dict) -> None:
    """Write tracker atomically via temp file + rename. Never raises."""
    try:
        TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json", prefix="woolworths_discount_",
            dir=str(TRACKER_PATH.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, TRACKER_PATH)
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception as exc:
        print(
            f"[woolworths_discounts] tracker write failed: {exc}",
            file=sys.stderr,
        )


def can_use_monthly_discount() -> bool:
    """True if the monthly discount has NOT been used in the current
    calendar month (YYYY-MM). Reads TRACKER_PATH; returns True if the file
    is missing/corrupt (fail-open). Never raises."""
    tracker = _read_tracker()
    if not tracker:
        return True
    last_used = tracker.get("last_used", "")
    current = _current_month()
    return last_used != current


def mark_monthly_discount_used() -> None:
    """Record the monthly discount as used in the current month.

    Writes {"last_used": "YYYY-MM", "history": [...]} atomically via temp
    file + rename. Appends to history (cap at 50 entries, oldest dropped).
    Never raises on I/O (stderr warning).
    """
    current = _current_month()
    ts = _current_iso()
    tracker = _read_tracker()
    if not tracker:
        tracker = {"last_used": current, "history": []}

    tracker["last_used"] = current
    if "history" not in tracker:
        tracker["history"] = []
    tracker["history"].append({"month": current, "timestamp": ts})
    # Cap history at 50 entries
    if len(tracker["history"]) > 50:
        tracker["history"] = tracker["history"][-50:]

    _write_tracker(tracker)


def monthly_discount_summary() -> dict:
    """Return {available: bool, last_used: str|None, history_len: int}.
    available = can_use_monthly_discount(). Never raises."""
    tracker = _read_tracker()
    return {
        "available": can_use_monthly_discount(),
        "last_used": tracker.get("last_used") if tracker else None,
        "history_len": len(tracker.get("history", [])) if tracker else 0,
    }


# ============================================================================
# Section F: Report formatter
# ============================================================================


def format_discount_report(
    items: list,
    team_discount_total: float,
    extra_discount_pct: float,
    extra_discount_savings: float,
) -> str:
    """Render a clean text block showing what discounts were applied.

    Lists each home-brand item that received the Team Discount with its
    original -> discounted price, the team discount total, and (if
    extra_discount_pct > 0) the extra discount line.
    Secret-free. If no discounts applied: "No discounts applied.".
    """
    lines = []
    if team_discount_total > 0:
        lines.append("**Team Discount (5% off Woolworths home-brand):**")
        for item in items:
            if isinstance(item, dict):
                applied = item.get("applied", False)
                name = item.get("name", "")
                orig = item.get("original_price", 0)
                disc = item.get("discounted_price", 0)
            else:
                applied = getattr(item, "applied", False)
                name = getattr(item, "name", "")
                orig = getattr(item, "original_price", 0)
                disc = getattr(item, "discounted_price", 0)
            if applied:
                lines.append(
                    f"  - {name}: ${orig:.2f} -> ${disc:.2f} "
                    f"(save ${orig - disc:.2f})"
                )
        lines.append(f"  Team Discount total: ${team_discount_total:.2f}")
        lines.append("")

    if extra_discount_pct > 0 and extra_discount_savings > 0:
        lines.append(
            f"**Extra Discount ({extra_discount_pct:.0f}% off "
            "Woolworths basket):**"
        )
        lines.append(f"  Extra savings: ${extra_discount_savings:.2f}")
        lines.append("")
    elif extra_discount_pct > 0:
        lines.append(
            f"**Extra Discount ({extra_discount_pct:.0f}%):** not applied "
            f"(already used this month)"
        )
        lines.append("")

    if not lines:
        lines.append("No discounts applied.")

    return "\n".join(lines)
