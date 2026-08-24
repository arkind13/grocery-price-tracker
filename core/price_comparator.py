#!/usr/bin/env python3
"""Dual-mode basket comparator across Woolworths, Coles, Aldi.

Modes: "sheet" (stored prices), "live" (API search), "auto" (sheet + live
fallback). Integrates Woolworths Team + Extra discounts.
"""
from __future__ import annotations
import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from core.sheets_sync import PRICE_COL, _find_col

STORES = ("woolworths", "coles", "aldi")
LIVE_STORES = ("woolworths", "coles")  # aldi: sheet-only (no live extractor)


# ============================================================================
# Section B: BasketItem dataclass
# ============================================================================


@dataclass(frozen=True)
class BasketItem:
    """A single product priced per store for basket comparison.

    Attributes:
        name: the query/generic name used for this item.
        prices: store -> float price. Stores with no match are simply
            absent from the dict (NOT 0.0 — the report flags them
            "not available at [store]").
        sources: store -> "sheet" | "live" (where each price came from).
        specials: store -> special_desc (empty string if none).
        brand: brand string (for home-brand detection).
        is_woolworths_home_brand: cached result of
            woolworths_discounts.is_woolworths_home_brand(name, brand).
    """
    name: str
    prices: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    specials: dict = field(default_factory=dict)
    brand: str = ""
    is_woolworths_home_brand: bool = False


# ============================================================================
# Section C: ComparisonReport dataclass
# ============================================================================


@dataclass(frozen=True)
class ComparisonReport:
    """Outcome of a basket comparison across stores.

    Attributes:
        items: list[BasketItem] (one per requested product, in order).
        raw_totals: store -> float sum of available prices (missing stores
            excluded; NOT zero-filled).
        store_coverage: store -> int count of items available at that store.
        team_discount_applied: bool.
        team_discount_savings: float total $ saved by Team Discount (>= 0).
        extra_discount_pct: float pct applied to Woolworths basket (0 if none).
        extra_discount_savings: float $ saved by Extra Discount (>= 0).
        final_totals: store -> float final total (after all discounts).
        cheapest_store: lowercase store id with the lowest final_total
            (None if no store has any price).
        most_expensive_store: lowercase store id with highest final_total.
        max_savings: float $ difference between cheapest and most expensive.
        warnings: human-readable, secret-free notices.
        not_available: dict store -> list[item names] missing at that store.
    """
    items: list = field(default_factory=list)
    raw_totals: dict = field(default_factory=dict)
    store_coverage: dict = field(default_factory=dict)
    team_discount_applied: bool = False
    team_discount_savings: float = 0.0
    extra_discount_pct: float = 0.0
    extra_discount_savings: float = 0.0
    final_totals: dict = field(default_factory=dict)
    cheapest_store: Optional[str] = None
    most_expensive_store: Optional[str] = None
    max_savings: float = 0.0
    warnings: list = field(default_factory=list)
    not_available: dict = field(default_factory=dict)


# ============================================================================
# Section D: compare_basket()
# ============================================================================


def compare_basket(
    product_names,            # str (comma/newline separated) OR list[str]
    *,
    mode: str = "auto",       # "sheet" | "live" | "auto"
    team_discount: bool = True,
    extra_discount_pct: float = 0.0,
    worksheet=None,           # optional pre-connected gspread Worksheet
) -> ComparisonReport:
    """Compare a basket of products across Woolworths, Coles, Aldi.

    Args:
        product_names: ingredient/product list (string or list).
        mode: "sheet" = stored prices only; "live" = live search all items;
            "auto" = sheet first, live fallback per item (default).
        team_discount: apply Woolworths 5% Team Discount on home-brand items.
        extra_discount_pct: 0-100. If > 0 AND can_use_monthly_discount(),
            apply X% to the entire Woolworths basket total (after Team
            Discount) and mark the monthly discount used.
        worksheet: optional pre-connected worksheet for tests/reuse.

    Returns:
        ComparisonReport. Never raises on a single missing item or a
        store with no match — records it in not_available / warnings.
    """
    from core.woolworths_discounts import (
        is_woolworths_home_brand,
        apply_team_discount,
        apply_extra_discount,
        can_use_monthly_discount,
        mark_monthly_discount_used,
    )

    # 1. Normalize names
    if isinstance(product_names, str):
        names = re.split(r"[,;\n]+", str(product_names))
        names = [n.strip() for n in names if n.strip()]
    else:
        names = [str(n).strip() for n in product_names if str(n).strip()]

    warnings = []

    if not names:
        return ComparisonReport(
            warnings=["No items provided for comparison"],
        )

    # 2. Gather prices per mode
    if mode == "sheet":
        items = _gather_sheet_prices(names, worksheet)
    elif mode == "live":
        items = _gather_live_prices(names)
    elif mode == "auto":
        # Rewired (Phase 9.2.h): use the lookup engine chain
        # Steps 1 -> 2 -> 3 (auto-pick) -> 5 (live search) -> 6.
        items = _gather_lookup_prices(names, worksheet)
    else:
        raise ValueError(
            f"Unknown mode '{mode}'. Use 'sheet', 'live', or 'auto'."
        )

    # 3. Compute is_woolworths_home_brand for each item
    for i, item in enumerate(items):
        if not item.is_woolworths_home_brand:
            hb = is_woolworths_home_brand(item.name, item.brand)
            items[i] = BasketItem(
                name=item.name,
                prices=dict(item.prices),
                sources=dict(item.sources),
                specials=dict(item.specials),
                brand=item.brand,
                is_woolworths_home_brand=hb,
            )

    # 4. Compute raw_totals per store
    raw_totals = {}
    store_coverage = {}
    not_available = {store: [] for store in STORES}
    for store in STORES:
        total = 0.0
        count = 0
        for item in items:
            if store in item.prices:
                total += item.prices[store]
                count += 1
            else:
                not_available[store].append(item.name)
        if count > 0:
            raw_totals[store] = round(total, 2)
            store_coverage[store] = count

    # 5. Woolworths discounts
    team_discount_applied = False
    team_discount_savings = 0.0
    extra_savings = 0.0
    extra_pct = 0.0

    woolworths_items_for_discount = []
    for item in items:
        if "woolworths" in item.prices:
            woolworths_items_for_discount.append({
                "name": item.name,
                "brand": item.brand,
                "price": item.prices["woolworths"],
            })

    if team_discount and woolworths_items_for_discount:
        discounted = apply_team_discount(
            woolworths_items_for_discount, "woolworths"
        )
        team_discount_applied = any(d["applied"] for d in discounted)
        team_discount_savings = round(
            sum(
                d["original_price"] - d["discounted_price"]
                for d in discounted
            ),
            2,
        )
        woolworths_post_team = round(
            sum(d["discounted_price"] for d in discounted), 2
        )
    elif "woolworths" in raw_totals:
        woolworths_post_team = raw_totals["woolworths"]
    else:
        woolworths_post_team = 0.0

    if extra_discount_pct > 0:
        extra_pct = float(extra_discount_pct)
        if can_use_monthly_discount():
            _, extra_savings = apply_extra_discount(
                woolworths_post_team, extra_pct
            )
            mark_monthly_discount_used()
        else:
            warnings.append(
                "Monthly discount already used this month — "
                "extra discount skipped"
            )
            extra_savings = 0.0

    # 6. final_totals
    final_totals = dict(raw_totals)
    if "woolworths" in final_totals:
        final_totals["woolworths"] = round(
            woolworths_post_team - extra_savings, 2
        )

    # 7. cheapest / most_expensive / max_savings
    stores_with_items = [
        s for s in STORES
        if s in final_totals and store_coverage.get(s, 0) > 0
    ]
    cheapest_store = None
    most_expensive_store = None
    max_savings = 0.0
    if stores_with_items:
        store_by_total = sorted(
            stores_with_items, key=lambda s: final_totals[s]
        )
        cheapest_store = store_by_total[0]
        most_expensive_store = store_by_total[-1]
        if cheapest_store != most_expensive_store:
            max_savings = round(
                final_totals[most_expensive_store]
                - final_totals[cheapest_store],
                2,
            )

    # Aldi note
    if not_available.get("aldi") and any(n for n in not_available["aldi"]):
        warnings.append(
            "Aldi has no live extractor — Aldi prices are sheet-only"
        )

    return ComparisonReport(
        items=items,
        raw_totals=raw_totals,
        store_coverage=store_coverage,
        team_discount_applied=team_discount_applied,
        team_discount_savings=team_discount_savings,
        extra_discount_pct=extra_pct if extra_savings > 0 else 0.0,
        extra_discount_savings=extra_savings,
        final_totals=final_totals,
        cheapest_store=cheapest_store,
        most_expensive_store=most_expensive_store,
        max_savings=max_savings,
        warnings=warnings,
        not_available=not_available,
    )


# ============================================================================
# Section E: _gather_sheet_prices()
# ============================================================================


def _gather_sheet_prices(
    names: list[str],
    worksheet=None,
) -> list[BasketItem]:
    """Build BasketItems from sheet prices only (exact + partial lookup).

    Uses RecipeResolver internals (SheetIndex) — exact then partial lookup
    per item. Does NOT call live search. For names with no sheet match:
    BasketItem with empty prices dict.
    """
    from core.recipe_resolver import RecipeResolver
    resolver = RecipeResolver(worksheet=worksheet)
    idx = resolver._ensure_index()

    items = []
    for name in names:
        prices = {}
        sources = {}
        specials = {}
        brand = ""

        exact = idx.find_exact(name)
        row = exact if exact is not None else idx.find_partial(name)

        if row is not None:
            prices = dict(row.prices)
            sources = {store: "sheet" for store in prices}
            specials = dict(row.specials)
            brand = row.brand

        items.append(BasketItem(
            name=name,
            prices=prices,
            sources=sources,
            specials=specials,
            brand=brand,
        ))
    return items


# ============================================================================
# Section F: _gather_live_prices()
# ============================================================================


def _gather_live_prices(names: list[str]) -> list[BasketItem]:
    """Build BasketItems from live search only (Woolworths + Coles).

    For each name: call fetch_woolworths_search + fetch_coles_search, take
    the FIRST result per store as the price. Aldi is never populated.
    Swallow network errors (store simply absent from prices).
    """
    from extractors.woolworths_extractor import fetch_woolworths_search
    from extractors.coles_extractor import fetch_coles_search

    items = []
    for name in names:
        prices = {}
        sources = {}
        specials = {}
        brand = ""

        try:
            ww_results = fetch_woolworths_search(name, page_size=5)
            for product in ww_results:
                if product.store.lower() == "woolworths":
                    prices["woolworths"] = product.price
                    sources["woolworths"] = "live"
                    if product.is_special and product.special_desc:
                        specials["woolworths"] = product.special_desc
                    if not brand and product.brand:
                        brand = product.brand
                    break
        except Exception as exc:
            print(
                f"[price_comparator] woolworths live failed "
                f"for '{name}': {exc}",
                file=sys.stderr,
            )

        try:
            coles_results = fetch_coles_search(name, page_size=5)
            for product in coles_results:
                if product.store.lower() == "coles":
                    prices["coles"] = product.price
                    sources["coles"] = "live"
                    if product.is_special and product.special_desc:
                        specials["coles"] = product.special_desc
                    if not brand and product.brand:
                        brand = product.brand
                    break
        except Exception as exc:
            print(
                f"[price_comparator] coles live failed "
                f"for '{name}': {exc}",
                file=sys.stderr,
            )

        items.append(BasketItem(
            name=name,
            prices=prices,
            sources=sources,
            specials=specials,
            brand=brand,
        ))
    return items


# ============================================================================
# Section F2: _gather_lookup_prices() — Phase 9.2.h lookup engine chain
# ============================================================================


def _gather_lookup_prices(
    names: list[str],
    worksheet=None,
) -> list[BasketItem]:
    """Build BasketItems via the lookup engine chain (Steps 1->2->3->5->6).

    Uses LookupEngine.find_product(interactive=False) which:
      - Step 1: exact Col A / Col I/J/K match  -> sheet prices
      - Step 2: Col P alias two-pass match      -> sheet prices
      - Step 3: auto-pick top partial candidate -> sheet prices
      - Step 5: live search Woolworths + Coles  -> live prices
      - Step 6: not found                       -> no prices

    Sources are tagged "sheet" or "live" accordingly.

    Args:
        names: list of product query strings.
        worksheet: optional pre-connected gspread Worksheet.

    Returns:
        list[BasketItem] one per name, in order.
    """
    from core.lookup import LookupEngine, LookupStatus

    engine = LookupEngine(worksheet=worksheet)
    items: list[BasketItem] = []
    for name in names:
        prices: dict = {}
        sources: dict = {}
        specials: dict = {}
        brand = ""

        try:
            result = engine.find_product(name, interactive=False)
        except Exception as exc:
            print(
                f"[price_comparator] lookup failed for '{name}': {exc}",
                file=sys.stderr,
            )
            result = None

        if result is not None:
            if result.status in (
                LookupStatus.EXACT_SHEET, LookupStatus.KEYWORD_ALIAS
            ):
                # Sheet prices from matched row (Step 1, 2, or auto-pick 3)
                prices = dict(result.prices)
                sources = {store: "sheet" for store in prices}
                specials = dict(result.specials)
                brand = result.brand
            elif result.status == LookupStatus.LIVE_SEARCH:
                # Live prices from store APIs (Step 5)
                prices = dict(result.prices)
                sources = {store: "live" for store in prices}
                specials = dict(result.specials)
                brand = result.brand

        items.append(BasketItem(
            name=name,
            prices=prices,
            sources=sources,
            specials=specials,
            brand=brand,
        ))
    return items


# ============================================================================
# Section G: format_report()
# ============================================================================


def format_report(report: ComparisonReport) -> str:
    """Render a Markdown table: item rows (name, woolworths, coles, aldi
    prices with store-source markers), then totals, discount lines
    (team + extra), cheapest store, and max savings.
    Top 25 items + a summary. Secret-free.
    """
    lines = []

    if not report.items:
        lines.append("**Basket Comparison:** No items provided.")
        return "\n".join(lines)

    # Header
    lines.append("| # | Product | Woolworths | Coles | Aldi |")
    lines.append("|---|---------|------------|-------|------|")

    # Items (top 25)
    for i, item in enumerate(report.items[:25], 1):
        ww = (
            f"${item.prices['woolworths']:.2f}"
            if "woolworths" in item.prices else "—"
        )
        cl = (
            f"${item.prices['coles']:.2f}"
            if "coles" in item.prices else "—"
        )
        al = (
            f"${item.prices['aldi']:.2f}"
            if "aldi" in item.prices else "—"
        )
        lines.append(f"| {i} | {item.name} | {ww} | {cl} | {al} |")

    if len(report.items) > 25:
        lines.append(
            f"| ... | *{len(report.items) - 25} more items* | | | |"
        )

    lines.append("")

    # Totals
    lines.append(
        "| Store | Raw Total | Items Available | Final Total |"
    )
    lines.append(
        "|-------|-----------|-----------------|-------------|"
    )
    for store in STORES:
        raw = (
            f"${report.raw_totals[store]:.2f}"
            if store in report.raw_totals else "—"
        )
        cov = report.store_coverage.get(store, 0)
        final = (
            f"${report.final_totals[store]:.2f}"
            if store in report.final_totals else "—"
        )
        lines.append(
            f"| {store.capitalize()} | {raw} | {cov} | {final} |"
        )
    lines.append("")

    # Discounts
    from core.woolworths_discounts import format_discount_report
    discount_items = []
    if report.team_discount_applied:
        for item in report.items:
            if item.is_woolworths_home_brand and "woolworths" in item.prices:
                disc_price = round(item.prices["woolworths"] * 0.95, 2)
                discount_items.append({
                    "name": item.name,
                    "brand": item.brand,
                    "original_price": item.prices["woolworths"],
                    "discounted_price": disc_price,
                    "applied": True,
                })
    discount_text = format_discount_report(
        discount_items,
        report.team_discount_savings,
        report.extra_discount_pct,
        report.extra_discount_savings,
    )
    if discount_text.strip():
        lines.append(discount_text)
        lines.append("")

    # Summary
    if report.cheapest_store:
        lines.append(
            f"**Cheapest store:** "
            f"{report.cheapest_store.capitalize()}"
        )
        if report.max_savings > 0:
            lines.append(
                f"**Max savings:** ${report.max_savings:.2f} "
                f"(vs {report.most_expensive_store.capitalize()})"
            )
    else:
        lines.append("**No prices available for any store.**")

    # Warnings
    if report.warnings:
        lines.append("")
        for w in report.warnings:
            lines.append(f"> ⚠ {w}")

    return "\n".join(lines)


# ============================================================================
# Section H: __main__ (CLI)
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare a basket of products across supermarkets"
    )
    parser.add_argument(
        "items", nargs="?", default="",
        help="Comma/newline/semicolon-separated product names"
    )
    parser.add_argument(
        "--mode", default="auto", choices=["sheet", "live", "auto"],
        help="Price source mode (default: auto)"
    )
    parser.add_argument(
        "--extra-discount", type=float, default=0.0,
        help="Extra discount percentage (0-100) to apply to Woolworths"
    )
    args = parser.parse_args()

    if not args.items:
        print(
            "Usage: python core/price_comparator.py 'milk, bread, eggs'",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        report = compare_basket(
            args.items,
            mode=args.mode,
            extra_discount_pct=args.extra_discount,
        )
        print(format_report(report))
        sys.exit(0)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
