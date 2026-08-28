#!/usr/bin/env python3
"""Woolworths discount engine: always-on display discounts.

Every displayed Woolworths price gets 5% off; Woolworths home-brand items
get an additional 5% on top (compounding => ~9.75% total). Coles and Aldi
prices are never discounted here. Discounts are DISPLAY-TIME only — the
Google Sheet always stores raw prices.

Also hosts: home-brand detection (32 canonical labels + macro alias),
the monthly Extra Discount helper, and the monthly usage tracker.
"""
from __future__ import annotations
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# Discount rates (spec §5). Base applies to EVERY Woolworths price;
# home-brand items get a second, compounded 5% off.
WOOLWORTHS_BASE_DISCOUNT = 0.05
HOME_BRAND_EXTRA_DISCOUNT = 0.05

# Canonical Woolworths home-brand list (spec §3) — single source of truth.
# Entries are pre-normalized via _normalize_brand_text(): lowercase,
# punctuation/apostrophes stripped, whitespace collapsed. 32 canonical
# names + the short-form "macro" alias for "Macro Wholefoods Market".
# NOTE: legacy substring labels "gold" and "free from" are intentionally
# DROPPED (false-positived on e.g. "Golden Circle", "Free From" ranges).
WOOLWORTHS_HOME_BRANDS = frozenset({
    # 32 canonical labels (normalized spellings)
    "apollo",
    "balnea",
    "baxters",
    "bell farms",
    "clean",
    "essentials",
    "farmers own",                # Farmer's Own
    "help at hand",
    "hillview",
    "inspire",
    "la gina",
    "la meida",
    "la mesita",
    "lantern alley",
    "little ones",
    "little wishes",
    "lolly go round",
    "macro wholefoods market",
    "market value",
    "plantitude",
    "ready chef",
    "smiling tums",
    "smitten",
    "strength meals co",
    "strike",
    "sushi izu",
    "the odd bunch",
    "thomas dux",
    "voeu",
    "woolworths bbq",
    "woolworths cook",
    "woolworths",                 # plain brand itself
    # short-form alias (live API often returns just "Macro")
    "macro",
})

# Monthly discount tracker (one use per calendar month).
TRACKER_PATH = (
    Path(__file__).resolve().parent.parent
    / "data" / "woolworths_discount_usage.json"
)


# ============================================================================
# Section B: Home-brand detection
# ============================================================================


def _normalize_brand_text(value) -> str:
    """Normalize brand/product text for matching.

    Lowercases, strips punctuation and apostrophes (so ``Farmer's Own``
    matches the stored ``farmers own``), and collapses internal whitespace.

    Args:
        value: raw brand or product-name string (None-safe).

    Returns:
        Normalized string ("" for empty/None input).
    """
    lowered = str(value or "").lower()
    stripped = re.sub(r"[^a-z0-9\s]", "", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def is_woolworths_home_brand(product_name: str, brand: str) -> bool:
    """True if the product is a Woolworths home-brand item.

    Detection order (spec §4 — exact matching only, NO free substring):
        1. both inputs empty -> False;
        2. normalized brand == "home" (the sheet Col G marker) -> True;
        3. normalized brand equals a WOOLWORTHS_HOME_BRANDS entry -> True;
        4. normalized brand starts with "woolworths" -> True;
        5. brand field EMPTY -> normalized product NAME starts with a list
           label at a word boundary (name == label OR name starts with
           label + space) -> True (rescues rows with blank Col G);
        6. otherwise False. A non-empty, non-matching brand always wins
           over the name fallback (avoids e.g. brand "Bega" + name
           "Woolworths Milk" being classified as home brand).

    Args:
        product_name: raw or generic product name (may be "" / None).
        brand: Brand_Type sheet cell or ProductItem.brand (may be "")..

    Returns:
        bool.
    """
    normalized_name = _normalize_brand_text(product_name)
    normalized_brand = _normalize_brand_text(brand)

    if not normalized_name and not normalized_brand:
        return False

    # Primary: brand-field match
    if normalized_brand == "home":
        return True
    if normalized_brand in WOOLWORTHS_HOME_BRANDS:
        return True
    if normalized_brand.startswith("woolworths"):
        return True

    # Fallback: leading word-boundary match on the product name,
    # ONLY when the brand field carries no information.
    if not normalized_brand:
        for label in WOOLWORTHS_HOME_BRANDS:
            if normalized_name == label or normalized_name.startswith(
                label + " "
            ):
                return True

    return False


# ============================================================================
# Section C: Always-on Woolworths discounts
# ============================================================================


def discounted_woolworths_price(price: float, is_home: bool) -> dict:
    """Compute the displayed price for one Woolworths item.

    Regular item: single 5% cut. Home-brand item: compounded cuts
    (round(round(price * 0.95, 2) * 0.95, 2)). Rounding is PER ITEM —
    totals must sum these rounded finals (spec §5).

    Args:
        price: raw shelf/promo price (> 0 expected, not enforced).
        is_home: whether the item is a Woolworths home-brand product.

    Returns:
        dict {"original": float, "final": float, "savings": float,
        "is_home": bool}. savings is original - final (rounded to cents).
    """
    original = float(price)
    base = round(original * (1 - WOOLWORTHS_BASE_DISCOUNT), 2)
    if is_home:
        final = round(base * (1 - HOME_BRAND_EXTRA_DISCOUNT), 2)
    else:
        final = base
    return {
        "original": original,
        "final": final,
        "savings": round(original - final, 2),
        "is_home": bool(is_home),
    }


def format_discounted_price(price: float, is_home: bool) -> str:
    """Format one Woolworths price for display surfaces.

    Shows ONLY the discounted price. The always-on team discount is
    deliberately NOT rendered as a "(was $X)" suffix — "was" annotations
    are reserved for genuine store specials, sourced from the store's
    WasPrice via was_price_from_special_desc().

    Args:
        price: raw shelf/promo price.
        is_home: whether the item is a Woolworths home-brand product
            (drives the compounded extra 5% off).

    Returns:
        str like "$4.51" for home brands or "$4.75" for regular items.
    """
    result = discounted_woolworths_price(price, is_home)
    return f"${result['final']:.2f}"


def was_price_from_special_desc(special_desc: str) -> Optional[float]:
    """Extract the GENUINE pre-special price from a special description.

    Both store extractors emit specials text of the form "Was $X.XX"
    (woolworths_extractor WasPrice / coles_extractor pricing.was). Only
    that genuine was-price may be displayed as "(was $X)" — sheet
    free-text descs like "Half Price" carry no was-price and yield None.

    Args:
        special_desc: specials description text (None-safe).

    Returns:
        float was-price when the description contains "Was $X", else
        None.
    """
    match = re.search(
        r"Was\s*\$\s*(\d+(?:\.\d+)?)",
        str(special_desc or ""),
        re.IGNORECASE,
    )
    if match:
        return float(match.group(1))
    return None


def apply_woolworths_discounts(items, store: str = "woolworths") -> list:
    """Apply always-on Woolworths display discounts to a basket.

    Every item gets the base 5% when store == woolworths; home-brand
    items additionally get the compounded extra 5%. Any other store is a
    no-op (prices returned unchanged, all flags False).

    Args:
        items: iterable of dicts OR duck-typed objects exposing
            .price/.brand/.raw_name (or .name) — ProductItem compatible.
        store: store id; only "woolworths" triggers discounts.

    Returns:
        list[dict], one per input item, each:
            {name, brand, original_price, base_price, discounted_price,
             applied: bool, home_extra_applied: bool, is_home: bool}
        base_price = round(original * 0.95, 2) — the single-discount
        intermediate (used to split savings reporting); absent extras
        leave discounted_price == base_price.
    """
    store_lower = (store or "").lower()
    is_ww = store_lower == "woolworths"
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

        original = float(price)
        if is_ww:
            is_home = is_woolworths_home_brand(name, brand)
            outcome = discounted_woolworths_price(original, is_home)
            results.append({
                "name": name,
                "brand": brand,
                "original_price": outcome["original"],
                "base_price": round(
                    original * (1 - WOOLWORTHS_BASE_DISCOUNT), 2
                ),
                "discounted_price": outcome["final"],
                "applied": True,
                "home_extra_applied": is_home,
                "is_home": is_home,
            })
        else:
            results.append({
                "name": name,
                "brand": brand,
                "original_price": original,
                "base_price": original,
                "discounted_price": original,
                "applied": False,
                "home_extra_applied": False,
                "is_home": False,
            })
    return results


# ============================================================================
# Section D: Extra Discount
# ============================================================================


def apply_extra_discount(basket_total: float, discount_pct: float) -> tuple:
    """Apply X% discount to a Woolworths basket total.

    Args:
        basket_total: the post-discount Woolworths total (>= 0).
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
    home_extra_total: float = 0.0,
    home_brand_count: int = 0,
    *,
    compact: bool = False,
) -> str:
    """Render the Telegram-style discount sub-block (spec §5.1).

    Structure (Telegram Style Kit — no markdown tables):
      * `🏷️ HOME BRAND EXTRA` sub-block — one `name · $base → $final`
        line per home-brand item, plus a `💰 Home extra: $x` total.
      * `🏷️ Extra X% · save $x` line when the monthly extra discount
        applied; a ⚠️ line when it was skipped (already used).
      * Base 5%: NO per-item lines (that is the compaction). A single
        summary line `🏷️ 5% off all WW items · save $x` is emitted ONLY
        in standalone mode (compact=False). Embedded callers (the basket
        report) pass compact=True because their tail line already
        summarises the base 5%.

    Secret-free. If nothing applies: "No discounts applied." (or an
    empty string in compact mode so embedders can skip the block).

    Args:
        items: per-item result dicts from apply_woolworths_discounts
            (duck-typed attribute access also supported).
        team_discount_total: summed BASE savings over all WW items.
        extra_discount_pct: monthly extra discount percent (0 = none).
        extra_discount_savings: dollar savings from that extra discount.
        home_extra_total: summed home-brand EXTRA savings (default 0.0).
        home_brand_count: number of home-brand WW items (default 0).
        compact: keyword-only. True when the output is embedded in a
            larger report whose tail summarises the base 5% (default
            False).

    Returns:
        Multi-line plain-text string ("" possible in compact mode).
    """

    def _get(item, key, default=None):
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    from core.telegram_format import subheader, kv, money, warn

    blocks = []

    # Base 5% — summary line only, standalone mode only.
    if not compact and team_discount_total > 0:
        blocks.append(
            f"🏷️ 5% off all WW items · save {money(team_discount_total)}"
        )

    # Home-brand extra — sub-block with per-item was -> now lines.
    if home_brand_count > 0 and home_extra_total > 0:
        home_lines = [subheader("HOME BRAND EXTRA", "🏷️")]
        for item in items:
            if _get(item, "home_extra_applied", False):
                home_lines.append(kv(
                    str(_get(item, "name", "")),
                    f"${_get(item, 'base_price', 0):.2f} \u2192 "
                    f"${_get(item, 'discounted_price', 0):.2f}",
                ))
        home_lines.append(f"💰 Home extra: {money(home_extra_total)}")
        blocks.append("\n".join(home_lines))

    # Monthly extra discount.
    if extra_discount_pct > 0 and extra_discount_savings > 0:
        blocks.append(
            f"🏷️ Extra {extra_discount_pct:.0f}% · "
            f"save {money(extra_discount_savings)}"
        )
    elif extra_discount_pct > 0:
        blocks.append(warn(
            f"Extra {extra_discount_pct:.0f}% not applied "
            f"(already used this month)"
        ))

    if not blocks:
        return "" if compact else "No discounts applied."

    return "\n\n".join(blocks)
