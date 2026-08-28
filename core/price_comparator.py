#!/usr/bin/env python3
"""Dual-mode basket comparator across Woolworths and Coles.

Modes: "sheet" (stored prices), "live" (API search), "auto" (sheet + live
fallback). Integrates the always-on Woolworths display discounts (base 5%
on all WW prices + compounded 5% home-brand extra) and the monthly Extra
Discount. The sheet itself always stores RAW prices.
"""
from __future__ import annotations
import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

from core.sheets_sync import PRICE_COL, _find_col

STORES = ("woolworths", "coles")
LIVE_STORES = ("woolworths", "coles")


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
        team_discount_savings: float total $ saved by the base 5% Woolworths
            discount, summed over ALL Woolworths items (>= 0).
        home_extra_savings: float additional $ saved by the compounded
            home-brand extra 5% (>= 0).
        home_brand_count: int number of Woolworths items classified as
            home-brand (and thus given the extra 5%).
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
    home_extra_savings: float = 0.0
    home_brand_count: int = 0
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
    """Compare a basket of products across Woolworths and Coles.

    Args:
        product_names: ingredient/product list (string or list).
        mode: "sheet" = stored prices only; "live" = live search all items;
            "auto" = sheet first, live fallback per item (default).
        team_discount: apply the always-on Woolworths display discounts
            (base 5% on ALL WW items + extra 5% on home brands). False
            shows raw prices.
        extra_discount_pct: 0-100. If > 0 AND can_use_monthly_discount(),
            apply X% to the entire Woolworths basket total (after the
            base/home discounts) and mark the monthly discount used.
        worksheet: optional pre-connected worksheet for tests/reuse.

    Returns:
        ComparisonReport. Never raises on a single missing item or a
        store with no match — records it in not_available / warnings.
    """
    from core.woolworths_discounts import (
        is_woolworths_home_brand,
        apply_woolworths_discounts,
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

    # 5. Woolworths discounts (always-on display discounts)
    team_discount_applied = False
    team_discount_savings = 0.0
    home_extra_savings = 0.0
    home_brand_count = 0
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
        discounted = apply_woolworths_discounts(
            woolworths_items_for_discount, "woolworths"
        )
        team_discount_applied = any(d["applied"] for d in discounted)
        # Base savings: 5% summed over ALL Woolworths items.
        team_discount_savings = round(
            sum(
                d["original_price"] - d["base_price"]
                for d in discounted
            ),
            2,
        )
        # Home-brand extra: compounded second 5% on home items only.
        home_extra_savings = round(
            sum(
                d["base_price"] - d["discounted_price"]
                for d in discounted
                if d["home_extra_applied"]
            ),
            2,
        )
        home_brand_count = sum(
            1 for d in discounted if d["home_extra_applied"]
        )
        # Final WW total = sum of per-item ROUNDED finals (spec §5).
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

    return ComparisonReport(
        items=items,
        raw_totals=raw_totals,
        store_coverage=store_coverage,
        team_discount_applied=team_discount_applied,
        team_discount_savings=team_discount_savings,
        home_extra_savings=home_extra_savings,
        home_brand_count=home_brand_count,
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
    the FIRST result per store as the price. Swallow network errors
    (store simply absent from prices).
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


def _format_ww_discounts_line(report: ComparisonReport, total: float) -> str:
    """Build the 🏷️ WW-discounts tail summary line (spec §5.1).

    Args:
        report: the ComparisonReport being rendered.
        total: summed WW savings (team + home extra + extra discount).

    Returns:
        str like "🏷️ WW discounts: −$0.75 (5% all $0.20 + 🏠 home extra
        $0.19 + extra 10% $0.36)", or "" when there is nothing to show.
    """
    from core.telegram_format import money

    parts = []
    if report.team_discount_savings > 0:
        parts.append(f"5% all {money(report.team_discount_savings)}")
    if report.home_extra_savings > 0:
        parts.append(f"🏠 home extra {money(report.home_extra_savings)}")
    if (
        report.extra_discount_savings > 0
        and report.extra_discount_pct > 0
    ):
        parts.append(
            f"extra {report.extra_discount_pct:.0f}% "
            f"{money(report.extra_discount_savings)}"
        )
    if not parts:
        return ""
    return f"🏷️ WW discounts: −{money(total)} ({' + '.join(parts)})"


def format_report(report: ComparisonReport) -> str:
    """Render the Telegram-style basket comparison (spec §5.1).

    Layout: 🛒 header + heavy divider, list-style item blocks with
    per-store price lines (🟢/🔴), a fenced box TOTALS table, the compact
    discounts sub-block, then the 🏆/🏷️/⚠️ tail. Top-25 cap with an
    overflow line. Pipe-free (no markdown tables), secret-free.
    """
    from core.telegram_format import (
        header, item_block, store_line, money, warn, fail, tail,
        fenced_table,
    )

    if not report.items:
        return header("Basket Comparison", "🛒") + "\nNo items provided."

    lines = [header("Basket Comparison", "🛒"), ""]

    # Items (top 25) — list-style blocks. WW shows the always-on
    # discounted price with the raw price visible; raw-only when the
    # discounts are off.
    from core.woolworths_discounts import format_discounted_price
    for i, item in enumerate(report.items[:25], 1):
        store_lines = []
        if "woolworths" in item.prices:
            if report.team_discount_applied:
                ww = format_discounted_price(
                    item.prices["woolworths"],
                    item.is_woolworths_home_brand,
                )
            else:
                ww = f"${item.prices['woolworths']:.2f}"
            store_lines.append(store_line("woolworths", ww))
        if "coles" in item.prices:
            store_lines.append(
                store_line("coles", f"${item.prices['coles']:.2f}")
            )
        lines.append(item_block(
            i, item.name, store_lines,
            home_brand=item.is_woolworths_home_brand,
        ))
        lines.append("")

    if len(report.items) > 25:
        lines.append(f"… +{len(report.items) - 25} more items")
        lines.append("")

    # Totals — fenced box table (Store / Raw / Final; — when no price).
    lines.append("📊 TOTALS")
    totals_rows = []
    for store in STORES:
        raw = (
            money(report.raw_totals[store])
            if store in report.raw_totals else "—"
        )
        final = (
            money(report.final_totals[store])
            if store in report.final_totals else "—"
        )
        totals_rows.append([store.capitalize(), raw, final])
    lines.append(fenced_table(
        ["Store", "Raw", "Final"], totals_rows, box=True
    ))
    lines.append("")

    # Discounts — consume the shared engine per item (NO inline recompute).
    # compact=True: the sub-block lists ONLY home-brand and extra-discount
    # lines; the base 5% is summarised in the 🏷️ tail line below.
    from core.woolworths_discounts import (
        format_discount_report,
        discounted_woolworths_price,
        WOOLWORTHS_BASE_DISCOUNT,
    )
    discount_items = []
    if report.team_discount_applied:
        for item in report.items:
            if "woolworths" not in item.prices:
                continue
            raw_price = item.prices["woolworths"]
            outcome = discounted_woolworths_price(
                raw_price, item.is_woolworths_home_brand
            )
            discount_items.append({
                "name": item.name,
                "brand": item.brand,
                "original_price": raw_price,
                "base_price": round(
                    raw_price * (1 - WOOLWORTHS_BASE_DISCOUNT), 2
                ),
                "discounted_price": outcome["final"],
                "applied": True,
                "home_extra_applied": item.is_woolworths_home_brand,
            })
    discount_text = format_discount_report(
        discount_items,
        report.team_discount_savings,
        report.extra_discount_pct,
        report.extra_discount_savings,
        home_extra_total=report.home_extra_savings,
        home_brand_count=report.home_brand_count,
        compact=True,
    )
    if discount_text.strip():
        lines.append(discount_text)
        lines.append("")

    # Tail: cheapest store, WW discounts summary, missing items, warnings.
    if report.cheapest_store:
        if report.max_savings > 0:
            lines.append(tail(
                report.cheapest_store.capitalize(),
                report.max_savings,
                vs=report.most_expensive_store.capitalize(),
            ))
        else:
            lines.append(
                f"🏆 Cheapest: {report.cheapest_store.capitalize()}"
            )
        ww_total_savings = round(
            report.team_discount_savings
            + report.home_extra_savings
            + report.extra_discount_savings,
            2,
        )
        if ww_total_savings > 0:
            ww_line = _format_ww_discounts_line(report, ww_total_savings)
            if ww_line:
                lines.append(ww_line)
    else:
        lines.append(fail("No prices available for any store."))

    for store, missing in report.not_available.items():
        if missing:
            noun = "item" if len(missing) == 1 else "items"
            lines.append(warn(
                f"{len(missing)} {noun} missing at {store.capitalize()}"
            ))

    for w in report.warnings:
        lines.append(warn(w))

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
