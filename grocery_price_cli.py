#!/usr/bin/env python3
"""Headless grocery-price CLI (Tool #14 entrypoint). Thin orchestration shell.

Delegates all business logic to grocery-price-tracker/core and /extractors.
Outputs clean Markdown to stdout; errors to stderr with exit code 1.
Never prints secrets (cookies, API keys, service-account JSON).
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent            # workspace root
_TRACKER = _HERE / "grocery-price-tracker"
if str(_TRACKER) not in sys.path:
    sys.path.insert(0, str(_TRACKER))

from core.sheets_client import _load_env            # noqa: E402
from core.telegram_format import (                  # noqa: E402
    header, subheader, fenced_table, item_block, store_line,
    kv, money, warn, ok, fail, tail, truncate, divider,
    unit_tag, unit_suffix, UNIT_UNAVAILABLE,
    HEAVY_DIVIDER, HEAVY_DIVIDER_WIDTH,
)

# Unicode constants (avoid backslash in f-string expressions for Py3.11 compat)
EM_DASH = "\u2014"
WARN = "\u26a0"
ARROW = "\u2192"


# ============================================================================
# Argparse skeleton
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grocery_price_cli.py",
        description="Headless grocery-price CLI (Tool #14)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("specials")
    sp.add_argument("--store", default="all", choices=["woolworths", "coles", "all"])
    sp.set_defaults(func=_cmd_specials)

    rp = sub.add_parser("rewards")
    rp.add_argument("--store", default="all", choices=["woolworths", "coles", "all"])
    rp.set_defaults(func=_cmd_rewards)

    cp = sub.add_parser("compare")
    cp.add_argument("--items", required=True)
    cp.add_argument("--extra-discount", type=float, default=0.0)
    cp.add_argument(
        "--team-discount", action=argparse.BooleanOptionalAction, default=None,
        help="Override the TEAM_DISCOUNT_ENABLED master switch for this "
             "call (default: follow the switch)",
    )
    cp.add_argument("--mode", default="auto", choices=["auto", "sheet", "live"])
    cp.set_defaults(func=_cmd_compare)

    sp2 = sub.add_parser("search")
    sp2.add_argument("--product", required=True)
    sp2.add_argument("--expand", action="store_true",
                     help="Show up to 8 results per store (display-only)")
    sp2.add_argument("--add-item", type=int, default=None, metavar="N",
                     help="Queue the Nth displayed result for Wednesday "
                          "(sheet row + searched-items queue; explicit add)")
    sp2.add_argument("--unit", default=None, metavar="UNIT",
                     help="Unit for --add-item when the result has none "
                          "(e.g. 1L / 250g / 5 pack, or the literal "
                          "'unit unavailable')")
    sp2.set_defaults(func=_cmd_search)

    rp2 = sub.add_parser("recipe")
    rp2.add_argument("--name", required=True)
    rp2.add_argument("--ingredients", required=True)
    rp2.add_argument("--extra-discount", type=float, default=0.0)
    rp2.set_defaults(func=_cmd_recipe)

    up = sub.add_parser("update")
    up.add_argument("--product", required=True)
    up.add_argument("--store", required=True, choices=["woolworths", "coles"])
    up.add_argument("--price", type=float, required=True)
    up.add_argument("--dry-run", action="store_true")
    up.set_defaults(func=_cmd_update)

    sy = sub.add_parser("sync")
    sy.add_argument("--force", action="store_true")
    sy.add_argument("--dry-run", action="store_true")
    sy.set_defaults(func=_cmd_sync)

    sc = sub.add_parser("specials-scan")
    sc.add_argument("--min-savings", type=int, default=50)
    sc.add_argument("--store", default="woolworths", choices=["woolworths"])
    sc.set_defaults(func=_cmd_specials_scan)

    um = sub.add_parser("unmapped")
    um.set_defaults(func=_cmd_unmapped)

    wd = sub.add_parser("wednesday")
    wd.add_argument("--dry-run", action="store_true",
                    help="Parse + match + report; skip sheet write, scp, Telegram")
    wd.add_argument("--no-scp", action="store_true",
                    help="Skip the VPS scp step (for local-only runs)")
    wd.add_argument("--no-telegram", action="store_true",
                    help="Skip the Telegram summary post")
    wd.add_argument("--source", default="docx", choices=["docx", "live"],
                    help="Item source: docx (default, byte-for-byte today's "
                         "behaviour) or live (window flush + fetch snapshots)")
    wd.set_defaults(func=_cmd_wednesday)

    lr = sub.add_parser(
        "live-refresh",
        help="Live window (LOCAL Windows machine only): login once -> "
             "flush queues -> fetch lists -> write snapshots",
    )
    lr.add_argument("--flush-only", action="store_true",
                    help="Run Phase B only (queue flush, no fetch)")
    lr.add_argument("--fetch-only", action="store_true",
                    help="Run Phase C only (list fetch, no flush)")
    lr.add_argument("--recapture", action="store_true",
                    help="Re-run the guided API discovery capture")
    lr.add_argument("--real-profile", action="store_true",
                    help="Seed logins from YOUR daily Chrome profile "
                         "(close Chrome fully first)")
    lr.add_argument("--cdp-port", type=int, default=None, metavar="PORT",
                    help="Attach to a Chrome already running with "
                         "--remote-debugging-port=PORT (advanced)")
    lr.set_defaults(func=_cmd_live_refresh)

    mp = sub.add_parser("map")
    mp.add_argument(
        "list_name",
        choices=["unmatched", "wool", "coles", "status"],
        help="Which list to resolve, or 'status' to show progress",
    )
    mp.add_argument("--next", action="store_true",
                    help="Non-interactive: resolve and show current item (for LLM/skill use)")
    mp.add_argument("--pick", type=int, default=None, metavar="N",
                    help="Non-interactive: pick candidate N, persist alias, advance")
    mp.add_argument("--add", action="store_true",
                    help="Non-interactive: add/update from current result, advance")
    mp.add_argument("--skip", action="store_true",
                    help="Non-interactive: skip current item, advance")
    mp.add_argument("--na", action="store_true",
                    help="Non-interactive: mark product NA at store (wool/coles only), advance")
    mp.add_argument("--forget", action="store_true",
                    help="Non-interactive: forget current item (unmatched only), advance")
    mp.add_argument("--keyword", type=str, default=None, metavar="STORE_NAME",
                    help="Non-interactive: save STORE_NAME as store keyword (wool/coles only), advance")
    mp.add_argument("--unit", default=None, metavar="UNIT",
                    help="Unit for --add when the result has none "
                         "(e.g. 1L / 250g / 5 pack, or the literal "
                         "'unit unavailable')")
    mp.set_defaults(func=_cmd_map)

    al = sub.add_parser(
        "add-to-list",
        help="Manual website-add queue: show pending / mark items done",
    )
    al.add_argument("action", choices=["show", "done"])
    al.add_argument("--items", default=None, metavar="N,N",
                    help="Item numbers from 'add-to-list show' (done only), "
                         "e.g. --items \"1,2,3\"")
    al.set_defaults(func=_cmd_add_to_list)

    sq = sub.add_parser(
        "searched-items",
        help="Searched-items queue (explicit Wednesday adds): show/remove/clear",
    )
    sq.add_argument("action", choices=["show", "remove", "clear"])
    sq.add_argument("--items", default=None, metavar="CODE,CODE",
                    help="Codes from 'searched-items show' (remove only), "
                         "e.g. --items \"KAT,RUM\"")
    sq.set_defaults(func=_cmd_searched_items)

    bk = sub.add_parser("backfill-keywords")
    bk.add_argument("--dry-run", action="store_true",
                    help="Print planned writes; no sheet mutation")
    bk.add_argument("--overwrite", action="store_true",
                    help="Also rewrite non-empty Col P cells (OFF by default)")
    bk.set_defaults(func=_cmd_backfill_keywords)

    bh = sub.add_parser(
        "backfill-home-brands",
        help="One-time Col G classifier backfill: write literal 'Home' "
             "for rows matching the canonical home-brand list",
    )
    bh.add_argument("--dry-run", action="store_true",
                    help="Print planned writes; no sheet mutation")
    bh.add_argument("--overwrite", action="store_true",
                    help="Also override non-empty non-matching Col G cells "
                         "when the Col A name matches the list")
    bh.set_defaults(func=_cmd_backfill_home_brands)

    bsz = sub.add_parser(
        "backfill-sizes",
        help="One-time Col C (size) backfill parsed from Col A/I/J "
             "names; fills only blank cells, never overwrites",
    )
    bsz.add_argument("--dry-run", action="store_true",
                     help="Print planned writes; no sheet mutation")
    bsz.set_defaults(func=_cmd_backfill_sizes)

    an = sub.add_parser(
        "analyze",
        help="Read-only sheet analysis (savings, home-brands, categories, etc.)",
    )
    an.add_argument(
        "--query", required=True,
        choices=["savings", "home-brands", "only-at",
                 "basket-savings", "categories", "specials", "rewards"],
        help="Type of analysis to run",
    )
    an.add_argument("--store", default=None,
                    choices=["woolworths", "coles"],
                    help="Store filter (for savings/only-at/specials)")
    an.add_argument("--limit", type=int, default=5,
                    help="Max items for savings query (default 5)")
    an.add_argument("--category", default=None,
                    help="Category filter (for home-brands query)")
    an.set_defaults(func=_cmd_analyze)

    tch = sub.add_parser(
        "topics-check",
        help="List forum topic names -> thread IDs (read-only, local)",
    )
    tch.set_defaults(func=_cmd_topics_check)
    return p


# ============================================================================
# Handler: _cmd_unmapped
# ============================================================================

def _cmd_unmapped(args) -> int:
    """Print pending unmapped items (top 25) — list style, no tables."""
    from core.name_matcher import get_pending_mappings

    pending = get_pending_mappings()
    if not pending:
        print("No pending unmapped items.")
        return 0

    lines = [header("Pending Unmapped Items", "📋"), ""]
    for i, item in enumerate(pending[:25], 1):
        cls = item.get("classification", {})
        row = (
            f"{i}. {truncate(item.get('raw_name', ''), 30)} "
            f"[{item.get('store', '')}]"
        )
        # A9: unit_tag never returns "" -> the size segment ALWAYS
        # shows (real size or the marker note, Rule A).
        detail = " · ".join(
            str(v) for v in (
                cls.get("brand", ""),
                unit_tag(cls.get("size", "")),
                cls.get("category", ""),
            ) if v
        )
        if detail:
            row += f" · {detail}"
        if item.get("count", ""):
            row += f" · x{item.get('count', '')}"
        lines.append(row)
    if len(pending) > 25:
        lines.append(f"… +{len(pending) - 25} more items")
    lines.append("")
    lines.append(f"📊 {len(pending)} pending unmapped item(s)")
    print("\n".join(lines))
    return 0


# ============================================================================
# Handler: _cmd_analyze (sheet-analyst skill — read-only)
# ============================================================================

def _cmd_analyze(args) -> int:
    """Run a read-only sheet analysis query and print a styled summary."""
    _load_env()
    from core import sheet_analyst

    q = args.query
    lines: list[str] = []

    if q == "savings":
        store = args.store or "woolworths"
        other = "coles" if store == "woolworths" else "woolworths"
        results = sheet_analyst.top_savings(
            store, other, limit=args.limit
        )
        lines.append(header(
            f"Top {args.limit} {store} savings vs {other}", "📊"
        ))
        lines.append(kv("Prices", "pre-discount"))
        lines.append("")
        if not results:
            lines.append(
                "No items where both stores are priced and the "
                "cheaper store wins."
            )
        else:
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {truncate(r['name'], 30)}")
                lines.append(
                    f"   {r['brand']} · {r['category']} · "
                    f"{money(r['cheaper_price'])} vs "
                    f"{money(r['pricier_price'])} · "
                    f"save {money(r['saving'])}"
                )

    elif q == "home-brands":
        result = sheet_analyst.count_home_brands(category=args.category)
        label = f" in {args.category}" if args.category else ""
        lines.append(header("Woolworths Home Brands", "📊"))
        lines.append(kv(f"Total{label}", str(result["total"])))
        lines.append("")
        if result["by_category"]:
            cat_rows = sorted(
                result["by_category"].items(), key=lambda x: -x[1]
            )
            lines.append(subheader("BY CATEGORY", "📊"))
            lines.append(fenced_table(
                ["Category", "Count"],
                [[cat, str(cnt)] for cat, cnt in cat_rows],
            ))

    elif q == "only-at":
        store = args.store or "woolworths"
        results = sheet_analyst.store_only_availability(store)
        lines.append(header(f"Items only at {store}", "📊"))
        lines.append(kv("Count", str(len(results))))
        lines.append("")
        if results:
            for i, r in enumerate(results[:25], 1):
                lines.append(f"{i}. {truncate(r['name'], 30)}")
                lines.append(
                    f"   {r['brand']} · {r['category']} · "
                    f"{money(r['price'])}"
                )
            if len(results) > 25:
                lines.append(f"… +{len(results) - 25} more items")

    elif q == "basket-savings":
        result = sheet_analyst.total_basket_savings("woolworths", "coles")
        lines.append(header("Total Basket Savings", "📊"))
        lines.append(kv("Prices", "pre-discount"))
        lines.append("")
        lines.append(kv("Items compared", str(result["items_compared"])))
        lines.append(kv("Total at Woolworths", money(result["total_at_a"])))
        lines.append(kv("Total at Coles", money(result["total_at_b"])))
        sav = result["saving"]
        if sav > 0:
            lines.append(kv("Saving at Woolworths", money(sav)))
        elif sav < 0:
            lines.append(kv("Saving at Coles", money(-sav)))
        else:
            lines.append("Both stores are equal.")

    elif q == "categories":
        results = sheet_analyst.category_breakdown()
        lines.append(header("Category Breakdown", "📊"))
        lines.append("")
        if not results:
            lines.append("No categorised items found.")
        else:
            lines.append(fenced_table(
                ["Category", "Count"],
                [[r["category"], str(r["count"])] for r in results],
            ))

    elif q == "specials":
        store = args.store
        count = sheet_analyst.count_specials(store=store)
        label = f" at {store.capitalize()}" if store else ""
        lines.append(f"📊 Items on special{label}: {count}")

    elif q == "rewards":
        count = sheet_analyst.count_rewards()
        lines.append(f"📊 Items with bonus rewards: {count}")

    print("\n".join(lines))
    return 0


# ============================================================================
# Handler: _cmd_rewards
# ============================================================================

def _cmd_rewards(args) -> int:
    """Print bonus rewards list (top 25) — list style, no tables."""
    _load_env()
    from core.specials_reporter import get_bonus_rewards

    store = None if args.store == "all" else args.store
    rewards = get_bonus_rewards(store=store)
    if not rewards:
        print("No bonus rewards (column O not populated).")
        return 0

    lines = [header("Bonus Rewards", "💰"), ""]
    from core.woolworths_discounts import (
        format_discounted_price,
        is_woolworths_home_brand,
    )
    for i, r in enumerate(rewards[:25], 1):
        # Discount ONLY when the reward's price came from the Woolworths
        # column (r["store"] set by get_bonus_rewards); others stay raw.
        if r.get("price") is not None and r.get("store") == "woolworths":
            price_str = format_discounted_price(
                r["price"],
                is_woolworths_home_brand(
                    r.get("name", ""), r.get("brand", "")
                ),
            )
        else:
            price_str = (
                f"${r['price']:.2f}" if r.get("price") is not None else EM_DASH
            )
        lines.append(
            f"{i}. {truncate(r['name'], 30)} · {r['rewards']} · {price_str}"
        )
    if len(rewards) > 25:
        lines.append(f"… +{len(rewards) - 25} more")
    lines.append("")
    lines.append(f"📊 {len(rewards)} bonus rewards")
    print("\n".join(lines))
    return 0


# ============================================================================
# Handler: _cmd_update
# ============================================================================

def _cmd_update(args) -> int:
    """Update a single product price in the sheet."""
    if args.price <= 0:
        print(f"Error: price must be > 0 (got {args.price})", file=sys.stderr)
        return 1

    _load_env()
    from core.sheets_sync import update_single_price

    result = update_single_price(
        args.product, args.store, args.price, dry_run=args.dry_run
    )
    if not result.get("found", False) or "error" in result:
        print(f"Error: {result.get('error', 'product not found')}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(
            f"[DRY RUN] Updated {args.store} price for '{args.product}' "
            f"(row {result.get('row_index')}): "
            f"{result.get('old_price')} \u2192 {result.get('new_price')} "
            f"(range {result.get('range_written')})"
        )
    else:
        print(
            f"Updated {args.store} price for '{args.product}' "
            f"(row {result.get('row_index')}): "
            f"{result.get('old_price')} \u2192 {result.get('new_price')} "
            f"(range {result.get('range_written')})"
        )
    return 0


# ============================================================================
# Handler: _cmd_compare
# ============================================================================

def _cmd_compare(args) -> int:
    """Compare basket across stores with optional discounts."""
    _load_env()
    from core.price_comparator import compare_basket, format_report
    from core.woolworths_discounts import TEAM_DISCOUNT_ENABLED

    # None -> follow the TEAM_DISCOUNT_ENABLED master switch; explicit
    # --team-discount / --no-team-discount force one behaviour.
    team_discount = (
        TEAM_DISCOUNT_ENABLED if args.team_discount is None
        else args.team_discount
    )
    report = compare_basket(
        args.items,
        mode=args.mode,
        team_discount=team_discount,
        extra_discount_pct=args.extra_discount,
    )
    print(format_report(report))
    return 0


# ============================================================================
# Handler: _cmd_recipe
# ============================================================================

def _cmd_recipe(args) -> int:
    """Resolve recipe ingredients and compare across stores."""
    _load_env()
    from core.price_comparator import compare_basket, format_report

    report = compare_basket(
        args.ingredients,
        mode="auto",
        team_discount=None,  # follows TEAM_DISCOUNT_ENABLED master switch
        extra_discount_pct=args.extra_discount,
    )
    print(header(f"Recipe — {args.name}", "🧾"))
    print(format_report(report))
    return 0


# ============================================================================
# Handler: _cmd_search
# ============================================================================

def _search_live_ranked(product: str, page_size: int) -> tuple[list, list, str]:
    """Search both stores and rank results per store (deterministic).

    Args:
        product (str): the search term.
        page_size (int): max results per store.

    Returns:
        tuple[list, list, str]: (ww_ranked, coles_ranked, coles_status)
        where coles_status is the extractor status string ("ok", "empty",
        "unavailable", "breaker_open", "cap_exceeded").
    """
    from extractors.woolworths_extractor import fetch_woolworths_search_noauth
    from extractors.coles_extractor import fetch_coles_search_status
    from core.lookup import rank_live_results

    ww_items: list = []
    try:
        ww_items = fetch_woolworths_search_noauth(product, page_size=page_size)
    except Exception as exc:
        print(warn(f"Woolworths live search unavailable: {exc}"),
              file=sys.stderr)

    coles_items: list = []
    coles_status = "unavailable"
    try:
        coles_items, coles_status = fetch_coles_search_status(
            product, page_size=page_size)
    except Exception as exc:
        print(warn(f"Coles live search unavailable: {exc}"), file=sys.stderr)

    ww_ranked = rank_live_results(product, ww_items)
    coles_ranked = rank_live_results(product, coles_items or [])
    return ww_ranked, coles_ranked, coles_status


def _print_queue_confirmation(entry: dict) -> None:
    """Print the EXACT §3.4 management phrases after a successful queue."""
    store = str(entry.get("store", "")).strip().capitalize()
    code = entry.get("code", "")
    # A6: ack shows the unit — 'X' · 200g (Coles) [KAT]; legacy
    # entries without "size" show the ⚠️ note.
    print(f"Queued for Wednesday: '{entry.get('keyword', '')}'"
          f"{unit_suffix(entry.get('size', ''))} ({store}) [{code}]")
    print(f"💬 Reply 'remove {code}' if this isn't the right product.")
    print("💬 'show searched items' any time to review the queue.")


def _queue_searched_item(store: str, keyword: str, generic_name: str,
                         store_product_id: str = "",
                         size: str = "") -> dict | None:
    """Queue one item on searched_items (dup-guarded) + print phrases.

    Returns:
        dict | None: the (new or existing) entry, or None when the queue
        write failed (error already printed).
    """
    from core import searched_items as si
    try:
        result = si.add_entry(
            store, keyword, generic_name,
            store_product_id=store_product_id, size=size)
    except (OSError, ValueError) as exc:
        print(f"searched_items write failed: {exc}")
        return None
    entry = result["entry"]
    if result["added"]:
        _print_queue_confirmation(entry)
    else:
        print(f"Already queued (since {si.since_label(entry)}): "
              f"'{entry.get('keyword', '')}' "
              f"({str(entry.get('store', '')).capitalize()}) "
              f"[{entry.get('code', '')}] — not added again")
    return entry


_UNIT_REQUIRED_ERROR = "unit is required: pass a size or the marker"


def _resolve_add_unit(name: str, live_size: str = "", *,
                      override: str = "", interactive: bool | None = None,
                      _input=input) -> str:
    """Resolve the unit for an add (Rule B chain, spec §4).

    Order: (1) explicit override (--unit flag), (2) live listing size,
    (3) size parsed from the product name via _SIZE_PATTERN, (4) ask
    the user once (D-U4; blank or 'unknown' -> marker), else fail fast
    (non-interactive one-shot runs, spec R1).

    Args:
        name (str): the product name being added.
        live_size (str): the live listing's size field ("" when absent).
        override (str): explicit --unit value ("" when not given).
        interactive (bool | None): force interactive mode; None =
            auto-detect via stdin TTY.
        _input: injectable input() for tests.

    Returns:
        str: a real size ("1L") or the canonical marker
        "unit unavailable".

    Raises:
        ValueError: _UNIT_REQUIRED_ERROR when nothing resolved and the
        session is non-interactive.
    """
    for candidate in (str(override or "").strip(),
                      str(live_size or "").strip()):
        if candidate:
            return candidate
    from core.name_matcher import _SIZE_PATTERN
    m = _SIZE_PATTERN.search(name or "")
    if m:
        return m.group(1).strip()
    if interactive is None:
        try:
            interactive = sys.stdin.isatty()
        except (ValueError, OSError):
            interactive = False
    if not interactive:
        raise ValueError(_UNIT_REQUIRED_ERROR)
    answer = str(_input(
        f"What unit is {name}? e.g. 1L / 250g / 5 pack — "
        f"reply, or 'unknown': ")).strip()
    if not answer or answer.lower() == "unknown":
        return UNIT_UNAVAILABLE
    return answer


def _cmd_search(args) -> int:
    """Pure live search across Woolworths + Coles (no sheet, display-only).

    Shows up to 3 ranked results per store (8 with --expand), continuous
    numbering. NEVER queues or writes anything (spec §3.4): the ONLY
    write path here is explicit `--add-item N`, which creates the sheet
    row (Col I/J stays EMPTY — interpretation 0.4) and queues the item
    on searched_items.
    """
    product = args.product.strip()
    if not product:
        print("Error: --product is required", file=sys.stderr)
        return 1

    page_size = 8 if getattr(args, "expand", False) else 3
    ww_ranked, coles_ranked, coles_status = _search_live_ranked(
        product, page_size)

    # The displayed list (exactly what the user numbered) — this is also
    # the pool `--add-item N` picks from (deterministic re-run, §0.3).
    displayed = ww_ranked[:page_size] + coles_ranked[:page_size]

    if getattr(args, "add_item", None) is not None:
        return _search_add_item(args, product, displayed)

    lines = [header(f"{product} — live prices", "🔍"), ""]

    count = 0
    cheapest_store = None
    cheapest_price = float("inf")

    # Always-on display discounts: WW lines show the discounted price
    # (no "(was ...)" suffix — genuine specials surface their own
    # "Was $x" text via the 🏷️ suffix). When the TEAM_DISCOUNT_ENABLED
    # master switch is off, raw prices are shown.
    from core.woolworths_discounts import (
        TEAM_DISCOUNT_ENABLED,
        discounted_woolworths_price,
        format_discounted_price,
        is_woolworths_home_brand,
    )

    def _size_suffix(item) -> str:
        # A1 (Rule A): never silently omit — unit_suffix yields
        # " · 1L" or " · ⚠️ unit unavailable".
        return unit_suffix(getattr(item, "size", "") or "")

    for item in ww_ranked[:page_size]:
        count += 1
        is_home = is_woolworths_home_brand(item.raw_name, item.brand)
        disp = format_discounted_price(item.price, is_home)
        if TEAM_DISCOUNT_ENABLED:
            ww_compare_price = discounted_woolworths_price(
                item.price, is_home
            )["final"]
        else:
            ww_compare_price = item.price
        store_lines = [store_line(
            "woolworths", disp + _size_suffix(item))]
        if item.is_special and item.special_desc:
            store_lines[0] += f"  🏷️ {item.special_desc}"
        lines.append(item_block(count, item.raw_name, store_lines))
        if ww_compare_price < cheapest_price:
            cheapest_price = ww_compare_price
            cheapest_store = "Woolworths"

    if coles_status in ("unavailable", "breaker_open", "cap_exceeded"):
        # B4.3: Woolworths-only answer + ONE ⚠️ line. No Coles block.
        if coles_status == "cap_exceeded":
            lines.append(warn(
                "Scrape.do per-run cap (40) reached — stopping Coles "
                "calls."))
        else:
            lines.append(warn("Coles not checked (unavailable)"))
    else:
        for item in coles_ranked[:page_size]:
            count += 1
            store_lines = [store_line(
                "coles", f"${item.price:.2f}" + _size_suffix(item))]
            if item.is_special and item.special_desc:
                store_lines[0] += f"  🏷️ {item.special_desc}"
            lines.append(item_block(count, item.raw_name, store_lines))
            if item.price < cheapest_price:
                cheapest_price = item.price
                cheapest_store = "Coles"

    if count == 0:
        lines.append(fail("No results found"))
    else:
        lines.append("")
        if cheapest_store:
            lines.append(
                f"🏆 Cheapest: {cheapest_store} at {money(cheapest_price)}"
            )
        # IN-9: light hint line — matches the "commands always printed"
        # UX without queueing anything.
        lines.append(
            "💬 Reply 'add item N' to queue a result for Wednesday.")

    print("\n".join(lines))
    return 0


def _search_add_item(args, product: str, displayed: list) -> int:
    """Handle `search --add-item N`: explicit add of the Nth result.

    Writes the sheet row via add_product_row with store_keyword="" (0.4),
    then queues the item on searched_items. Sheet write failure => error
    line, NOTHING queued (the two stay consistent).

    Args:
        args: parsed CLI args (add_item, expand).
        product (str): the search term (becomes the Col P alias).
        displayed (list): the ranked results in displayed order.

    Returns:
        int: 0 on success, 1 on validation/write failure.
    """
    n = args.add_item
    if not (1 <= n <= len(displayed)):
        print(f"Error: --add-item {n} is out of range — this search "
              f"shows {len(displayed)} result(s).", file=sys.stderr)
        return 1

    chosen = displayed[n - 1]
    store = chosen.store.lower()

    # Rule B: resolve the unit BEFORE any write (live size -> name
    # parse -> --unit -> ask -> fail-fast; spec §4).
    try:
        unit = _resolve_add_unit(
            chosen.raw_name,
            getattr(chosen, "size", "") or "",
            override=getattr(args, "unit", None) or "")
    except ValueError as exc:
        print(f"Error: {exc} — re-run with --unit \"1L\" or "
              f"--unit \"unit unavailable\"", file=sys.stderr)
        return 1

    # Sheet row first; Col I/J stays EMPTY (interpretation 0.4).
    _load_env()
    from core.sheets_sync import add_product_row
    try:
        res = add_product_row(
            generic_name=chosen.raw_name,
            store=store,
            price=chosen.price,
            brand=chosen.brand,
            size=unit,
            category=chosen.category,
            store_keyword="",
            alias=product,
            is_special=chosen.is_special,
            special_desc=chosen.special_desc,
        )
    except Exception as exc:
        print(f"add_product_row failed: {exc}")
        return 1
    if not res.get("wrote"):
        print(f"Add failed: {res.get('error', 'unknown')}")
        return 1
    print(ok(f"Added '{chosen.raw_name}' to sheet "
             f"(row {res.get('row_index')}, {store} "
             f"${chosen.price:.2f})"))
    print(ok(f"Alias '{product}' saved to Col P."))

    # Then the Wednesday queue (Queue 2).
    _queue_searched_item(
        store, chosen.raw_name, chosen.raw_name,
        store_product_id=getattr(chosen, "product_id", "") or "",
        size=unit)
    return 0


# ============================================================================
# Stub handlers (defined in Part B — sync, specials, specials-scan)
# ============================================================================

def _cmd_specials(args) -> int:
    """Active specials: Mode B (sheet) + Mode A (live list, Woolworths only)."""
    _load_env()
    from core.specials_reporter import get_active_specials, format_specials_report

    store = None if args.store == "all" else args.store
    specials = get_active_specials(store=store)
    print(format_specials_report(specials, store))

    # Mode A: live saved-list specials (Woolworths only, best-effort)
    if store is None or store == "woolworths":
        try:
            from extractors.woolworths_extractor import fetch_woolworths_list
            ww_items = fetch_woolworths_list()
            live_specials = [
                i for i in ww_items if i.is_special
            ]
            if live_specials:
                print("")
                print(subheader(
                    "SAVED-LIST SPECIALS — LIVE SCAN", "🏷️"
                ))
                for i, item in enumerate(live_specials[:25], 1):
                    disp = _product_price_display("woolworths", item)
                    detail = item.special_desc or EM_DASH
                    print(f"{i}. {truncate(item.raw_name, 30)}")
                    print(f"   {disp}  ·  {detail}")
                print(f"📊 {len(live_specials)} live specials")
        except Exception:
            print("")
            print(warn("Woolworths live list unavailable (cookie missing/expired)"))

    return 0


def _cmd_sync(args) -> int:
    """Extract saved lists, match, batch-write to sheet, + queue summary."""
    _load_env()

    from extractors.woolworths_extractor import fetch_woolworths_list
    from extractors.coles_extractor import fetch_coles_list
    from core.name_matcher import (
        NameMatcher, load_keyword_index, get_pending_mappings,
    )
    from core.sheets_sync import sync_prices
    from core.missing_items_tracker import update_missing_items, format_missing_summary

    warnings = []

    # 1. Woolworths list
    ww_items = []
    try:
        ww_items = fetch_woolworths_list()
    except Exception as exc:
        warnings.append(f"Woolworths list fetch failed: {exc}")

    # 2. Coles list
    coles_items = []
    try:
        coles_items = fetch_coles_list()
    except Exception as exc:
        warnings.append(f"Coles list fetch failed: {exc}")

    # 3. Match
    index = load_keyword_index()
    matcher = NameMatcher(index)

    ww_results  = matcher.match_batch(ww_items)
    coles_results = matcher.match_batch(coles_items)

    all_results = ww_results + coles_results
    all_items   = ww_items + coles_items

    # 4. Missing-items diff
    missing_summary = update_missing_items(ww_results, coles_results)

    # 5. Sync to sheet
    if not all_results and not all_items:
        print("Error: both store lists returned empty and no items to sync",
              file=sys.stderr)
        return 1

    report = sync_prices(all_results, all_items, dry_run=args.dry_run)

    # 6. Print sync summary
    lines = [header("Sync Report", "🔄")]
    synced = set(report.stores_synced or [])
    for store in ("woolworths", "coles"):
        if store in synced:
            lines.append(ok(f"{store.capitalize()} · synced"))
        else:
            lines.append(fail(f"{store.capitalize()} · not synced"))
    lines.append("")
    lines.append("📊 COUNTS")
    count_rows = [
        ["Rows examined", str(report.rows_examined)],
        ["Rows updated", str(report.rows_updated)],
        [
            "Items matched/skipped",
            f"{report.items_matched}/{report.items_skipped}",
        ],
        ["Stores synced", ", ".join(report.stores_synced) or "none"],
    ]
    if not args.dry_run:
        count_rows.append(["Range written", report.range_written or "—"])
    else:
        count_rows.append(["Mode", "DRY RUN (no sheet write)"])
    count_rows.append(["Timestamp", report.timestamp])
    lines.append(fenced_table(["Metric", "Value"], count_rows))
    lines.append("")

    # 7. Queue summary
    lines.append("📋 QUEUE SUMMARY")
    lines.append(format_missing_summary())
    lines.append("")

    # 8. Warnings
    for w in warnings:
        lines.append(warn(w))
    for w in report.warnings:
        lines.append(warn(w))

    print("\n".join(lines))
    return 0


def _cmd_specials_scan(args) -> int:
    """Site-wide deep-discount scan (Tier 2, best-effort) + saved-list scan (Tier 1)."""
    import re

    lines = [
        header(f"Deep Discounts — min {args.min_savings}% savings", "🏷️"),
        "",
    ]

    results = []

    # Tier 2: site-wide browse (best-effort)
    tier2_ok = False
    try:
        from extractors.woolworths_extractor import fetch_woolworths_specials_browse
        browse_items = fetch_woolworths_specials_browse(
            min_savings_pct=args.min_savings, page_size=48
        )
        if browse_items:
            tier2_ok = True
            for item in browse_items:
                # Compute savings_pct from WasPrice in special_desc
                savings_pct = 0
                was_price = None
                m = re.search(r"Was \$(\d+\.?\d*)", item.special_desc or "")
                if m:
                    was_price = float(m.group(1))
                    if was_price > 0 and item.price > 0:
                        savings_pct = round((was_price - item.price) / was_price * 100)
                if savings_pct >= args.min_savings:
                    regular_str = f"${was_price:.2f}" if was_price else EM_DASH
                    results.append({
                        "name": item.raw_name,
                        "brand": item.brand,
                        "regular": regular_str,
                        "sale": item.price,
                        "savings_pct": savings_pct,
                        "store": item.store.capitalize(),
                    })
    except Exception:
        pass

    if not tier2_ok:
        print(warn("Site-wide specials browse unavailable — falling back to saved-list scan."),
              file=sys.stderr)

    # Tier 1: saved-list specials (always works if cookie present)
    try:
        from extractors.woolworths_extractor import fetch_woolworths_list
        ww_items = fetch_woolworths_list()
        for item in ww_items:
            if not item.is_special:
                continue
            savings_pct = 0
            was_price = None
            m = re.search(r"Was \$(\d+\.?\d*)", item.special_desc or "")
            if m:
                was_price = float(m.group(1))
                if was_price > 0 and item.price > 0:
                    savings_pct = round((was_price - item.price) / was_price * 100)
            if savings_pct >= args.min_savings:
                regular_str = f"${was_price:.2f}" if was_price else "\u2014"
                # Avoid duplicates if already in Tier 2
                already_in = any(
                    r["name"] == item.raw_name for r in results
                )
                if not already_in:
                    results.append({
                        "name": item.raw_name,
                        "brand": item.brand,
                        "regular": regular_str,
                        "sale": item.price,
                        "savings_pct": savings_pct,
                        "store": item.store.capitalize(),
                    })
    except Exception as exc:
        print(f"> {WARN} Saved-list scan unavailable: {exc}", file=sys.stderr)

    # Sort by savings_pct descending (raw special depth — unchanged).
    results.sort(key=lambda r: r["savings_pct"], reverse=True)

    # Sale column shows the always-on discounted price; the Regular
    # column and savings-% stay raw per spec.
    from core.woolworths_discounts import (
        format_discounted_price,
        is_woolworths_home_brand,
    )
    # Sale line shows the always-on discounted price; the Regular
    # price and savings-% stay raw per spec.
    from core.woolworths_discounts import (
        format_discounted_price,
        is_woolworths_home_brand,
    )
    for i, r in enumerate(results[:25], 1):
        sale_disp = format_discounted_price(
            r["sale"],
            is_woolworths_home_brand(r["name"], r.get("brand", "")),
        )
        lines.append(f"{i}. {truncate(r['name'], 30)} · {r['store']}")
        lines.append(
            f"   Sale {sale_disp} · Regular {r['regular']} · "
            f"save {r['savings_pct']}%"
        )

    if len(results) > 25:
        lines.append(f"… +{len(results) - 25} more items")

    lines.append("")
    lines.append(f"📊 {len(results)} item(s) with \u2265{args.min_savings}% savings")

    if not results:
        lines.append(warn("No items found matching the minimum savings threshold."))

    print("\n".join(lines))
    return 0


# ============================================================================
# Handler: _cmd_wednesday — ONE command does the entire Wednesday sync
# ============================================================================

# VPS target for scp of the 3 list files (host path; container mounts this volume).
_VPS_HOST = "ubuntu@169.58.107.0"
_VPS_DATA_DIR = "/home/ubuntu/openclaw/tasks/ai-tools/grocery-price-tracker/data"

# Telegram routing (mirror telegram_gateway/topics.py + allowlist.py constants).
_TELEGRAM_CHAT_ID = -1004394070843
# D24: 151 (grocery-sync-sheet) RETIRED — never post to it. IDs verified
# via M1 (topics-check, 2026-08-30); env overrides win (A8).
_SPECIALS_THREAD_ID = 206   # specials-wool topic; env TELEGRAM_SPECIALS_TOPIC_ID
_WEEKLY_THREAD_ID = 208     # weekly-lists topic; env TELEGRAM_WEEKLY_TOPIC_ID
_TELEGRAM_USER_ID = 1594431983


def _int_env(env_var: str, fallback):
    """Integer env override (A8): valid digits win, else the fallback.

    Args:
        env_var: environment variable name.
        fallback: int | None returned when the env var is unset/invalid.

    Returns:
        int | None
    """
    raw = (os.environ.get(env_var) or "").strip()
    if raw.lstrip("-").isdigit():
        return int(raw)
    return fallback

# Column indices in Products_Master (0-based) — keyword columns used for
# cross-store "missing" detection (mirror name_matcher.KeywordIndex).
_WW_KW_COL = 8     # I (Search_Keyword_Woolworths)
_COLES_KW_COL = 9  # J (Search_Keyword_Coles)

# Stores to parse from .docx files.
_DOCX_STORES = ("woolworths", "coles")


def _send_telegram(bot_token, chat_id, text, message_thread_id=None):
    """Best-effort Telegram message send. Never raises — returns ok bool.

    Args:
        bot_token (str): Telegram bot token.
        chat_id (int | str): Target chat.
        text (str): Message body (truncated to 4096 chars).
        message_thread_id (int | None): Forum topic thread ID.

    Returns:
        bool: True when the API returned ok.
    """
    import json as _json
    import urllib.parse as _url
    import urllib.request as _req
    payload = {"chat_id": chat_id, "text": text[:4096]}
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    try:
        data = _url.urlencode(payload).encode()
        req = _req.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage", data=data
        )
        with _req.urlopen(req, timeout=15) as resp:
            body = _json.loads(resp.read().decode("utf-8", errors="replace"))
        return bool(body.get("ok"))
    except Exception:
        return False


def _chunk_list_message(title: str, items: list, limit: int = 4000) -> list:
    """Build resolve-list message bodies, chunked to <= limit chars (A4).

    Args:
        title: list title (e.g. "Unmatched").
        items: item strings (may be empty).
        limit: max chars per message part.

    Returns:
        list[str]: message bodies; >1 part each carries "(part N/M)".
    """
    if not items:
        return [f"📋 {title}: none"]
    lines = [f"📋 {title} ({len(items)}):", ""]
    lines.extend(f"• {name}" for name in items)
    text = "\n".join(lines)
    # Reserve room for the "(part N/M)" suffix INSIDE every part — no
    # part may exceed `limit` chars with its suffix included (A4).
    total = max(1, -(-len(text) // limit))
    while True:
        reserve = len(f"\n(part {total}/{total})") if total > 1 else 0
        size = limit - reserve
        parts = [text[i:i + size] for i in range(0, len(text), size)]
        if len(parts) == total:
            break
        total = len(parts)
    out = []
    for n, part in enumerate(parts, 1):
        suffix = f"\n(part {n}/{total})" if total > 1 else ""
        out.append(part + suffix)
    return out


def _unmatched_display_line(entry: dict) -> str:
    """Telegram resolve-list line for one pending unmapped entry (A9)."""
    size = (entry.get("classification") or {}).get("size", "")
    return (f"{entry.get('raw_name', '')} [{entry.get('store', '')}]"
            f"{unit_suffix(size)}")


def _unmatched_display_lines(pending: list) -> list:
    """Telegram resolve-list lines for pending unmapped entries (A9)."""
    return [_unmatched_display_line(e) for e in pending]


def _missing_display_line(generic: str, size: str) -> str:
    """Telegram resolve-list line for one wool/coles-missing row (A9)."""
    return f"{generic}{unit_suffix(size)}"


def _post_weekly_summary(bot_token: str, summary_text: str,
                         resolve_lists: list) -> None:
    """Step 7 (D24): summary DM + weekly-lists; lists to weekly-lists only.

    resolve_lists: list of (title, items) tuples. Unset weekly topic ID ->
    DM-only with a console note (never posts, never crashes).
    """
    weekly_topic = _int_env("TELEGRAM_WEEKLY_TOPIC_ID", _WEEKLY_THREAD_ID)
    dm_ok = _send_telegram(bot_token, _TELEGRAM_USER_ID, summary_text)
    if weekly_topic is None:
        print("  weekly-lists topic ID unset — summary DM-only "
              "(set TELEGRAM_WEEKLY_TOPIC_ID or fill the M1 IDs)")
    else:
        topic_ok = _send_telegram(
            bot_token, _TELEGRAM_CHAT_ID, summary_text,
            message_thread_id=weekly_topic)
        print(f"  Weekly-lists topic: {'OK' if topic_ok else 'FAILED'}")
        for title, items in resolve_lists:
            bodies = _chunk_list_message(title, items)
            for body in bodies:
                _send_telegram(
                    bot_token, _TELEGRAM_CHAT_ID, body,
                    message_thread_id=weekly_topic)
            print(f"  {title} list → weekly-lists: "
                  f"{len(bodies)} message(s)")
    print(f"  DM: {'OK' if dm_ok else 'FAILED'}")


def _post_specials_report(bot_token: str, spec_text: str) -> None:
    """Step 8 (D24): specials report DM + specials-wool topic."""
    specials_topic = _int_env(
        "TELEGRAM_SPECIALS_TOPIC_ID", _SPECIALS_THREAD_ID)
    spec_dm = _send_telegram(bot_token, _TELEGRAM_USER_ID, spec_text)
    if specials_topic is None:
        print("  specials-wool topic ID unset — specials DM-only "
              "(set TELEGRAM_SPECIALS_TOPIC_ID or fill the M1 IDs)")
    else:
        spec_topic = _send_telegram(
            bot_token, _TELEGRAM_CHAT_ID, spec_text,
            message_thread_id=specials_topic)
        print(f"  Specials Topic: {'OK' if spec_topic else 'FAILED'}")
    print(f"  Specials DM: {'OK' if spec_dm else 'FAILED'}")


def _write_list_file(path, items, header_line):
    """Write a plain-text list file (one item per line) to data/.

    Args:
        path (Path): Target .txt path.
        items (list[str]): Lines to write (one per item).
        header_line (str): First line (comment header).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header_line, ""]
    lines.extend(items)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _reset_list_action_progress(data_dir):
    """Reset the per-list resume index so the map flow starts fresh.

    Args:
        data_dir (Path): grocery-price-tracker/data/ directory.
    """
    import json as _json
    progress = {
        "unmatched": 0,
        "wool": 0,
        "coles": 0,
    }
    path = data_dir / "list_action_progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(progress, indent=2), encoding="utf-8")


def _extract_woolworths_specials(doc_path):
    """Extract genuine specials from ``Woolworths_Specials.docx``.

    Only items carrying a discount marker are returned — regular-priced
    lines are excluded so the Telegram report lists actual specials, not
    every product in the doc.

    Recognised markers (on the line directly below the current price):
      * ``SAVE $X.XX`` — dollar-off special. Discount % is computed as
        ``save / (price + save) * 100`` relative to the original price.
      * ``N FOR $XXX`` — multi-buy bundle special (e.g. ``2 for $4.50``).

    The Woolworths saved-list layout is three lines per special::

        <Product Name>
        $<current price>
        <detail line: "save $1.53" or "2 for $4.50">

    Args:
        doc_path: Path to the ``.docx`` file.

    Returns:
        list of dicts with keys ``name`` (str), ``price`` (float current
        price), ``detail`` (human-readable special text), and
        ``discount_pct`` (float for save specials, None for multi-buy).
    """
    from extractors.specials_parser import detect_special
    try:
        from docx import Document
    except ImportError:
        print(
            "[specials] python-docx not installed — cannot parse specials doc",
            file=sys.stderr,
        )
        return []

    if not os.path.isfile(doc_path):
        return []

    doc = Document(doc_path)
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    specials = []
    used = set()

    for idx, line in enumerate(lines):
        # detect_special encapsulates the SAVE forward-look / FOR backward-look
        # dual logic (shared with doc_parser.parse_docx via specials_parser).
        name, price, detail, discount_pct = detect_special(lines, idx)

        if name and price and detail and name not in used:
            used.add(name)
            specials.append({
                "name": name,
                "price": price,
                "detail": detail,
                "discount_pct": discount_pct,
            })

    return specials


def _build_ww_specials_lines(specials_items: list) -> list:
    """Build the Wednesday Woolworths-specials list-style lines.

    Always-on display discounts applied to the current price. Docx rows
    carry no brand field, so home brands are classified via the
    leading-label product-name fallback (spec §6 surface #7).

    Args:
        specials_items: list of dicts {name, price, detail} from
            _extract_woolworths_specials.

    Returns:
        list[str] plain-text lines ending with a 📊 count line
        (max 40 items).
    """
    from core.woolworths_discounts import (
        format_discounted_price,
        is_woolworths_home_brand,
    )
    spec_lines = [header("Woolworths Specials", "🏷️"), ""]
    for i, item in enumerate(specials_items[:40], 1):
        disp = format_discounted_price(
            item["price"],
            is_woolworths_home_brand(item.get("name", ""), ""),
        )
        spec_lines.append(f"{i}. {truncate(item['name'], 30)}")
        price_line = f"   {disp}"
        if item.get("detail"):
            price_line += f"  ·  {item['detail']}"
        spec_lines.append(price_line)
    if len(specials_items) > 40:
        spec_lines.append(f"… +{len(specials_items) - 40} more items")
    spec_lines.append("")
    spec_lines.append(f"📊 {len(specials_items)} specials")
    return spec_lines


def _cmd_wednesday(args) -> int:
    """Wednesday grocery sync — ONE command does everything.

    Pipeline:
        1. Parse .docx files (Woolworths/Coles) -> ProductItem lists
        2. Match against sheet keyword index (exact, headless, no prompts)
        3. Batch-sync prices to Google Sheet (D/E)
        4. Generate 3 list files: unmatched.txt, wool_missing.txt, coles_missing.txt
        5. scp the 3 lists to VPS (so Claw can serve the map flow)
        6. Reset list_action_progress.json
        7. Send Telegram summary + specials to user DM + grocery-sync-sheet topic

    Replaces the legacy interactive name_importer.py + local_sync.py flow.
    """
    import os
    import subprocess

    _load_env()

    from extractors.doc_parser import parse_docx_cache, parse_docx
    from core.name_matcher import (
        NameMatcher, load_keyword_index, get_pending_mappings,
    )
    from core.sheets_sync import sync_prices
    from core.missing_items_tracker import (
        update_missing_items, get_missing_items, format_missing_summary,
    )
    from core.sheets_client import connect_worksheet

    data_dir = _TRACKER / "data"
    warnings = []
    live_source = getattr(args, "source", "docx") == "live"
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    flush_summary = None

    # --- Step 0 (live source only): pull queue files from the VPS ------
    if live_source:
        from extractors import live_list_fetch as llf
        from extractors import session_refresh as sr

        if args.dry_run:
            print(warn("Step 0: [DRY RUN] live window flush would be "
                       "skipped; fetch + validation still run (IN-8)"))
        print(header("Wednesday Grocery Sync (live)", "📅"))
        print()
        print("Step 0: Pulling queue files from VPS (best-effort)...")
        queue_pull_ok = True
        if args.dry_run or args.no_scp:
            print("  (skipped: dry-run / --no-scp — using local copies)")
            queue_pull_ok = False
        else:
            for queue_file in ("add_to_list.json", "searched_items.json"):
                remote = f"{_VPS_HOST}:{_VPS_DATA_DIR}/{queue_file}"
                local = data_dir / queue_file
                result_scp = subprocess.run(
                    ["scp", "-o", "ConnectTimeout=10", remote, str(local)],
                    capture_output=True, text=True, timeout=30,
                )
                if result_scp.returncode == 0:
                    print(f"  Pulled {queue_file} from VPS")
                else:
                    queue_pull_ok = False
            if not queue_pull_ok:
                print(warn("VPS queue pull failed — proceeding with "
                           "local copies"))

        # Live window (login -> flush -> fetch) unless today's snapshots
        # already exist (WC-9). Dry-run skips the FLUSH only (IN-8).
        if not all(p.exists()
                   for p in llf.required_snapshot_paths(date_str)):
            print()
            print("Live window: opening browser (flush -> fetch)...")
            window_summary = sr.run(
                flush=not args.dry_run, fetch=True)
            flush_summary = window_summary
            for store in ("woolworths", "coles"):
                store_summary = window_summary.get(store, {})
                login = "OK" if store_summary.get("login") else "FAILED"
                print(f"  {store.capitalize()}: login {login}")
                discovery = (window_summary.get("discovery") or {}).get(store)
                if discovery == "captured":
                    print(f"    discovery: captured")
                elif discovery is not None:
                    print(f"    discovery: failed — run "
                          f"'live-refresh --recapture' to train")
                flush_result = store_summary.get("flush")
                if isinstance(flush_result, dict):
                    added = flush_result.get("added", [])
                    failed = flush_result.get("failed", [])
                    parked = flush_result.get("parked", [])
                    print(f"    flush: {len(added)} added, "
                          f"{len(failed)} failed, {len(parked)} parked")
                    if flush_result.get("reason"):
                        print(f"      reason: {flush_result['reason']}")
                    for failed_item in failed:
                        print(f"      NEEDS ATTENTION: "
                              f"{failed_item.get('keyword', '')}")
                fetch_result = store_summary.get("fetch")
                if isinstance(fetch_result, dict):
                    state = "OK" if fetch_result.get("ok") else \
                        f"FAILED ({fetch_result.get('reason', 'unknown')})"
                    print(f"    fetch: {state}")
        else:
            print("Live window: today's snapshots already exist — "
                  "skipping (WC-9)")
            flush_summary = {}

        # All-or-nothing gate BEFORE any sheet write (§5.2).
        try:
            llf.validate_complete(date_str)
        except ValueError as exc:
            print()
            print(fail(str(exc)))
            return 1
        print(ok("Live snapshots complete."))

    # --- Step 1: Parse .docx files ---
    print(header("Wednesday Grocery Sync", "📅"))
    print()
    if live_source:
        print("Step 1: Reading live snapshots...")
        store_items = {}
        snapshots = llf.snapshots_for_date(date_str)
        for store in _DOCX_STORES:
            items = snapshots.get(store, [])
            store_items[store] = items
            snapshot_note = ok(store.capitalize() + ": " + str(len(items))
                               + " items from snapshot")
            print(f"  {snapshot_note}")
    else:
        print("Step 1: Parsing Word documents...")
        store_items = {}
        for store in _DOCX_STORES:
            try:
                items = parse_docx_cache(store)
                store_items[store] = items
                print(f"  {ok(store.capitalize() + ': ' + str(len(items)) + ' items parsed')}")
            except Exception as exc:
                store_items[store] = []
                warnings.append(f"{store} docx parse failed: {exc}")
                print(f"  {fail(store.capitalize() + ': FAILED (' + str(exc) + ')')}")

    all_items = []
    for store in _DOCX_STORES:
        all_items.extend(store_items.get(store, []))

    if not all_items:
        print()
        print("Error: no items parsed from any .docx file.", file=sys.stderr)
        return 1

    print(f"  Total: {len(all_items)} items across {len(store_items)} store(s)")

    # --- Step 2: Match against sheet keyword index ---
    print()
    print("Step 2: Matching against sheet keyword index...")
    index = load_keyword_index()
    matcher = NameMatcher(index)

    all_results = []
    per_store_results = {}
    for store in _DOCX_STORES:
        items = store_items.get(store, [])
        if not items:
            per_store_results[store] = []
            continue
        results = matcher.match_batch(items)
        per_store_results[store] = results
        all_results.extend(results)
        matched = sum(1 for r in results if r.matched)
        print(f"  {store.capitalize()}: {matched}/{len(items)} matched")

    # --- Step 3: Sync prices to sheet ---
    print()
    if args.dry_run:
        print(warn("Step 3: [DRY RUN] Skipping sheet write"))
        report = sync_prices(all_results, all_items, dry_run=True)
    else:
        print("Step 3: Syncing prices to Google Sheet...")
        report = sync_prices(all_results, all_items, dry_run=False)
    print(f"  Rows examined: {report.rows_examined}")
    print(f"  Rows updated: {report.rows_updated}")
    print(f"  Items matched: {report.items_matched} / skipped: {report.items_skipped}")
    print(f"  Stores synced: {report.stores_synced}")
    if not args.dry_run and report.range_written:
        print(f"  Range written: {report.range_written}")

    # --- Step 4: Generate 3 list files ---
    print()
    print("Step 4: Generating list files...")

    # 4-pre. Pull ignored_items.txt from VPS so the local run sees items the
    # user forgot via Telegram (forget writes on the VPS; this sync brings
    # them back locally before we filter unmatched). Non-fatal on failure.
    if not args.dry_run and not args.no_scp:
        remote_ignored = f"{_VPS_HOST}:{_VPS_DATA_DIR}/ignored_items.txt"
        local_ignored = data_dir / "ignored_items.txt"
        result_scp = subprocess.run(
            ["scp", "-o", "ConnectTimeout=10", remote_ignored, str(local_ignored)],
            capture_output=True, text=True, timeout=30,
        )
        if result_scp.returncode == 0:
            print("  Pulled ignored_items.txt from VPS")
        # Silently skip if the file doesn't exist yet on VPS (first run).

    # 4a. unmatched.txt — items from .docx that didn't match any sheet keyword
    pending = get_pending_mappings()
    # Exclude items the user permanently forgot via `map unmatched --forget`.
    ignored = set(_read_ignored_items(data_dir))

    def _machine_line(e: dict) -> str:
        return f"{e.get('raw_name', '')} [{e.get('store', '')}]"

    pending_visible = [e for e in pending
                       if _machine_line(e) not in ignored]
    if len(pending_visible) != len(pending):
        print(f"  (excluded {len(pending) - len(pending_visible)} "
              f"forgotten items)")
    # Machine lines feed unmatched.txt (parsed by `map unmatched`);
    # display lines carry units for Telegram only (plan P5).
    unmatched_lines = [_machine_line(e) for e in pending_visible]
    unmatched_display = _unmatched_display_lines(pending_visible)
    unmatched_path = data_dir / "unmatched.txt"
    _write_list_file(
        unmatched_path, unmatched_lines,
        f"# Unmatched items (parsed from .docx but no keyword hit) — {len(unmatched_lines)} total",
    )
    print(f"  unmatched.txt: {len(unmatched_lines)} items")

    # 4b. wool_missing.txt — rows where Col J (Coles keyword) is present but
    #     Col I (Woolworths keyword) is empty -> missing from Woolworths.
    # 4c. coles_missing.txt — rows where Col I (Woolworths keyword) is present
    #     but Col J (Coles keyword) is empty -> missing from Coles.
    #
    # NOTE: the list population AND the file writes both live inside the
    # `if not args.dry_run` guard. Previously the writers ran unconditionally,
    # so a --dry-run would clobber the real lists with empty "0 total" files
    # (root cause of the stale "wool/coles showing 0" bug).
    wool_missing_lines = []
    coles_missing_lines = []
    wool_missing_display = []   # Telegram-only lines with units (P5)
    coles_missing_display = []
    if not args.dry_run:
        # Re-read the sheet to compare keyword columns I and J per row
        ws = connect_worksheet()
        all_values = ws.get_all_values()
        rows = all_values[1:] if len(all_values) > 1 else []
        for row in rows:
            generic = row[0].strip() if row else ""
            if not generic:
                continue
            size_c = row[2].strip() if len(row) > 2 else ""
            ww_kw = row[_WW_KW_COL].strip() if len(row) > _WW_KW_COL else ""
            coles_kw = row[_COLES_KW_COL].strip() if len(row) > _COLES_KW_COL else ""
            # "NA" (set by the `na` action) counts as populated -> excluded.
            if coles_kw and not ww_kw:
                wool_missing_lines.append(generic)
                wool_missing_display.append(
                    _missing_display_line(generic, size_c))
            if ww_kw and not coles_kw:
                coles_missing_lines.append(generic)
                coles_missing_display.append(
                    _missing_display_line(generic, size_c))

        wool_path = data_dir / "wool_missing.txt"
        _write_list_file(
            wool_path, wool_missing_lines,
            f"# Sheet rows with a Coles keyword (J) but no Woolworths keyword (I) — {len(wool_missing_lines)} total",
        )
        print(f"  wool_missing.txt: {len(wool_missing_lines)} items")

        coles_path = data_dir / "coles_missing.txt"
        _write_list_file(
            coles_path, coles_missing_lines,
            f"# Sheet rows with a Woolworths keyword (I) but no Coles keyword (J) — {len(coles_missing_lines)} total",
        )
        print(f"  coles_missing.txt: {len(coles_missing_lines)} items")
    else:
        print("  wool_missing.txt: (dry-run — skipped, existing file preserved)")
        print("  coles_missing.txt: (dry-run — skipped, existing file preserved)")

    # --- Step 5: scp the 3 lists to VPS ---
    scp_ok = False
    if not args.dry_run and not args.no_scp:
        print()
        print("Step 5: scp list files to VPS...")
        list_files = [unmatched_path, wool_path, coles_path]
        try:
            for lf in list_files:
                result = subprocess.run(
                    ["scp", "-o", "ConnectTimeout=10", str(lf),
                     f"{_VPS_HOST}:{_VPS_DATA_DIR}/{lf.name}"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    warnings.append(f"scp {lf.name} failed: {result.stderr.strip()}")
                    print(f"  {lf.name}: FAILED")
                else:
                    print(f"  {lf.name}: OK")
            scp_ok = True
        except Exception as exc:
            warnings.append(f"scp step failed: {exc}")
            print(f"  scp failed: {exc}")
    elif args.dry_run:
        print()
        print("Step 5: [DRY RUN] Skipping scp")

    # --- Step 6: Reset list_action_progress.json ---
    if not args.dry_run:
        print()
        print("Step 6: Resetting list_action_progress.json...")
        _reset_list_action_progress(data_dir)
        print("  OK (all indices reset to 0)")

    # --- Step 7: Telegram summary + specials ---
    if not args.dry_run and not args.no_telegram:
        print()
        print("Step 7: Sending Telegram summary...")

        # Build summary text — pre-styled for Telegram (plain text).
        summary_lines = [
            header("Wednesday Sync Complete"
                   + (" (live)" if live_source else ""), "📅"),
            "",
            kv("Source", "live snapshots" if live_source else "docx"),
            kv("Items parsed", str(len(all_items))),
            kv(
                "Items matched/skipped",
                f"{report.items_matched}/{report.items_skipped}",
            ),
            kv("Rows updated", str(report.rows_updated)),
            kv("Stores synced", ", ".join(report.stores_synced) or "none"),
            "",
            "📋 LISTS",
            kv("Unmatched", str(len(unmatched_lines))),
            kv(
                "Woolworths missing (has Coles kw, no Woolies kw)",
                str(len(wool_missing_lines)),
            ),
            kv(
                "Coles missing (has Woolies kw, no Coles kw)",
                str(len(coles_missing_lines)),
            ),
            "",
            # Queue summary is built inline from the freshly-built lists
            # (NOT format_missing_summary() — that reads orphaned JSON
            # queues that wednesday never populates via
            # update_missing_items(), so it would show stale 0/0
            # contradicting the real counts above).
            "📊 QUEUE SUMMARY",
            f"📋 Unmapped items: {len(unmatched_lines)}",
            fail(
                f"Woolworths missing items "
                f"(on Coles list, not at Woolworths): "
                f"{len(wool_missing_lines)}"
            ),
            fail(
                f"Coles missing items "
                f"(on Woolworths list, not at Coles): "
                f"{len(coles_missing_lines)}"
            ),
        ]

        # Append scp status
        if scp_ok:
            summary_lines.append("")
            summary_lines.append(ok("Lists deployed to VPS."))
        elif args.no_scp:
            summary_lines.append("")
            summary_lines.append(warn("VPS scp skipped (--no-scp)."))

        # Append the live-window flush report (failed items by exact
        # name) when running with --source live (WC-12).
        if live_source and isinstance(flush_summary, dict):
            for store in ("woolworths", "coles"):
                store_flush = (flush_summary.get(store, {}) or {}).get("flush")
                if not isinstance(store_flush, dict):
                    continue
                failed = store_flush.get("failed", [])
                parked = store_flush.get("parked", [])
                if failed or parked:
                    summary_lines.append("")
                    summary_lines.append(
                        warn(f"{store.capitalize()} flush needs "
                             f"attention:"))
                    for failed_item in failed:
                        summary_lines.append(
                            fail(f"- {failed_item.get('keyword', '')}"
                                 f"{unit_suffix(failed_item.get('size', ''))}"))
                    for parked_item in parked:
                        summary_lines.append(
                            fail(f"- {parked_item.get('keyword', '')} "
                                 f"(parked)"
                                 f"{unit_suffix(parked_item.get('size', ''))}"))

        # Append map instruction
        summary_lines.append("")
        summary_lines.append(
            "Reply `map unmatched` / `map wool` / `map coles` to resolve "
            "the lists one item at a time."
        )

        # Append warnings
        for w in warnings:
            summary_lines.append(warn(w))
        for w in report.warnings:
            summary_lines.append(warn(w))

        summary_text = "\n".join(summary_lines)

        # Send to user DM + weekly-lists topic; resolve lists to the topic
        bot_token = os.environ.get("TELEGRAM_CLAW_BOT", "")
        if bot_token:
            _post_weekly_summary(bot_token, summary_text, [
                ("Unmatched", unmatched_display),
                ("Woolworths missing", wool_missing_display),
                ("Coles missing", coles_missing_display),
            ])
        else:
            print("  TELEGRAM_CLAW_BOT not set — skipping Telegram")
    elif args.dry_run:
        print()
        print("Step 7: [DRY RUN] Skipping Telegram")

    # --- Step 8: Woolworths Specials report ---
    # Docx path: parse Woolworths_Specials.docx (same name->price format
    # as other docs). Live path: read the WW Special-list snapshot taken
    # by the live window. Both feed the SAME Telegram report below.
    # Non-fatal when the source is missing.
    specials_items = None
    specials_doc_path = _TRACKER / "Woolworths_Specials.docx"
    if live_source:
        from extractors.live_list_fetch import (
            specials_from_live, ww_snapshot_path, WW_SPECIALS_SLUG,
        )
        specials_snapshot = ww_snapshot_path(date_str, WW_SPECIALS_SLUG)
        if not specials_snapshot.is_file():
            print()
            print("Step 8: Woolworths specials snapshot not found — "
                  "skipping specials report")
            warnings.append("Woolworths specials snapshot not found — "
                            "no specials report sent")
        else:
            print()
            print("Step 8: Reading Woolworths specials from live "
                  "snapshot...")
            try:
                specials_items = [
                    {"name": i.raw_name, "price": i.price,
                     "detail": i.special_desc or ""}
                    for i in specials_from_live(date_str)
                ]
                print(f"  {len(specials_items)} specials found "
                      f"(from live snapshot)")
            except Exception as exc:
                specials_items = None
                warnings.append(f"Woolworths specials snapshot parse "
                                f"failed: {exc}")
                print(f"  FAILED: {exc}")
    elif not specials_doc_path.is_file():
        print()
        print("Step 8: Woolworths_Specials.docx not found — skipping specials report")
        warnings.append("Woolworths_Specials.docx not found — no specials report sent")
    else:
        print()
        print("Step 8: Parsing Woolworths specials report...")
        try:
            specials_items = _extract_woolworths_specials(str(specials_doc_path))
            print(f"  {len(specials_items)} specials found (save / multi-buy only)")
        except Exception as exc:
            specials_items = None
            warnings.append(f"Woolworths specials parse failed: {exc}")
            print(f"  FAILED: {exc}")

    if specials_items is not None:
        if args.dry_run:
            print("  [DRY RUN] Skipping Telegram specials report")
        elif args.no_telegram:
            print("  --no-telegram: skipping Telegram specials report")
        elif specials_items:
            spec_lines = _build_ww_specials_lines(specials_items)

            spec_text = "\n".join(spec_lines)
            bot_token = os.environ.get("TELEGRAM_CLAW_BOT", "")
            if bot_token:
                _post_specials_report(bot_token, spec_text)
            else:
                print("  TELEGRAM_CLAW_BOT not set — skipping specials report")
        else:
            print("  No save/multi-buy specials found")

    # --- Final output ---
    print()
    print(divider(HEAVY_DIVIDER, HEAVY_DIVIDER_WIDTH))
    if args.dry_run:
        print(warn("DRY RUN COMPLETE — no sheet write, no scp, no Telegram"))
    else:
        print(ok("WEDNESDAY SYNC COMPLETE"))
    print(divider(HEAVY_DIVIDER, HEAVY_DIVIDER_WIDTH))
    return 0


# ============================================================================
# Handler: _cmd_live_refresh — live window (LOCAL machine only)
# ============================================================================

def _cmd_live_refresh(args) -> int:
    """Run the live window: login once -> flush queues -> fetch lists.

    LOCAL WINDOWS MACHINE ONLY (headed browser + AU residential IP) —
    the agent NEVER invokes this subcommand; SKILL.md guides the user to
    run it locally. Phases:

        default        Phase A -> B -> C
        --flush-only   Phase A -> B
        --fetch-only   Phase A -> C
        --recapture    guided API discovery, then the requested phases
        --real-profile seed logins from your daily Chrome profile
                       (close Chrome fully first)

    A browser-less environment (VPS/CI) gets a clear error, not a trace.

    Args:
        args: Parsed argparse Namespace (flush_only, fetch_only,
        recapture, real_profile).

    Returns:
        int: 0 when every requested phase succeeded for both stores,
        1 otherwise.
    """
    _load_env()
    from extractors import session_refresh as sr

    flush = not getattr(args, "fetch_only", False)
    fetch = not getattr(args, "flush_only", False)

    print(header("Live Refresh", "🔄"))
    cdp_port = getattr(args, "cdp_port", None)
    if getattr(args, "real_profile", False) and cdp_port:
        print(fail("--real-profile and --cdp-port are mutually "
                   "exclusive"), file=sys.stderr)
        return 1
    if cdp_port:
        print(f"Attaching to Chrome on localhost:{cdp_port} (headed)…")
    elif getattr(args, "real_profile", False):
        print("Opening the live window (seeded from your daily Chrome, "
              "headed)…")
    else:
        print("Opening the live window (local Chrome, headed)…")
    try:
        summary = sr.run(flush=flush, fetch=fetch,
                         recapture=getattr(args, "recapture", False),
                         real_profile=getattr(args, "real_profile", False),
                         cdp_port=cdp_port)
    except RuntimeError as exc:
        print(fail(str(exc)), file=sys.stderr)
        return 1
    except Exception as exc:
        print(fail(f"Live window failed: {exc}"), file=sys.stderr)
        return 1

    ok_all = True
    print()
    for store in ("woolworths", "coles"):
        store_summary = summary.get(store, {})
        login_ok = bool(store_summary.get("login"))
        print(subheader(store.capitalize(),
                        "🟢" if store == "woolworths" else "🔴"))
        print(kv("Login", "OK" if login_ok else "FAILED"))
        discovery = (summary.get("discovery") or {}).get(store)
        if discovery == "captured":
            print(kv("Discovery", "captured"))
        elif discovery is not None:
            print(kv(
                "Discovery",
                "failed — run 'live-refresh --recapture' to train"))
        if not login_ok:
            ok_all = False
        for phase in ("flush", "fetch"):
            phase_result = store_summary.get(phase)
            if phase_result is None:
                print(kv(phase.capitalize(), "skipped"))
                continue
            if isinstance(phase_result, dict):
                if phase_result.get("ok", True):
                    print(kv(phase.capitalize(), "OK"))
                    if phase == "flush":
                        added = phase_result.get("added", [])
                        failed = phase_result.get("failed", [])
                        parked = phase_result.get("parked", [])
                        print(kv("Added", str(len(added))))
                        print(kv("Failed", str(len(failed))))
                        print(kv("Parked", str(len(parked))))
                        if phase_result.get("reason"):
                            print(kv("Reason", phase_result["reason"]))
                        for failed_item in failed:
                            print(f"  {fail(failed_item.get('keyword', ''))}")
                else:
                    ok_all = False
                    print(kv(phase.capitalize(), "FAILED"))
                    print(f"  {fail(phase_result.get('reason', 'unknown'))}")
            else:
                print(kv(phase.capitalize(), str(phase_result)))

    print()
    if ok_all:
        print(ok("Live refresh complete."))
        return 0
    print(warn("Live refresh finished with failures — see above."))
    return 1


# ============================================================================
# Handler: _cmd_topics_check — M1 helper (read-only, LOCAL machine only)
# ============================================================================

def _cmd_topics_check(args) -> int:
    """List forum topic names → thread IDs visible to the bot.

    Calls getUpdates ONCE and prints every forum-topic creation event
    (name → message_thread_id) plus every recent topic message
    (thread id · text head). Read-only: never posts. This is how the
    D24 topic IDs are discovered (M1 step 7).

    Args:
        args: parsed argparse Namespace (no options).

    Returns:
        int: 0 on success, 1 when the bot token is missing or the API
        call fails.
    """
    _load_env()
    bot_token = os.environ.get("TELEGRAM_CLAW_BOT", "")
    if not bot_token:
        print("Error: TELEGRAM_CLAW_BOT not set in env/.env",
              file=sys.stderr)
        return 1
    import json as _json
    import urllib.request as _req
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    try:
        with _req.urlopen(_req.Request(url), timeout=15) as resp:
            body = _json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        print(f"Error: getUpdates failed: {exc}", file=sys.stderr)
        return 1
    if not body.get("ok"):
        print(f"Error: getUpdates not ok: "
              f"{body.get('description', '')}", file=sys.stderr)
        return 1
    seen = set()
    found = 0
    for upd in body.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        thread_id = msg.get("message_thread_id")
        if thread_id is None:
            continue
        ftc = msg.get("forum_topic_created") or {}
        name = ftc.get("name")
        key = (thread_id, name or (msg.get("text") or "")[:40])
        if key in seen:
            continue
        seen.add(key)
        if name:
            print(f"{name} → {thread_id}")
        else:
            print(f"{thread_id} · {(msg.get('text') or '')[:40]}")
        found += 1
    if not found:
        print("No topic messages visible. Send '@ClawArkindBot id' in "
              "each topic, then re-run.")
    return 0


# ============================================================================
# Handler: _cmd_map — interactive one-item-at-a-time list resolution
# ============================================================================

_LIST_FILES = {
    "unmatched": "unmatched.txt",
    "wool": "wool_missing.txt",
    "coles": "coles_missing.txt",
}


def _read_list_file(path) -> list[str]:
    """Read a .txt list file, skipping comment (#) and blank lines.

    Args:
        path: Path to the .txt file.

    Returns:
        list of item strings (one per non-comment, non-blank line).
    """
    if not path.is_file():
        return []
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _read_ignored_items(data_dir: Path) -> set:
    """Return the set of permanently-forgotten unmatched item lines.

    Reads data/ignored_items.txt (created by `map unmatched --forget`, 9.6).
    Each stored line is the exact formatted unmatched item string
    ("ProductName [store]"). Returns an empty set if the file is absent.

    Args:
        data_dir (Path): grocery-price-tracker/data/ directory.

    Returns:
        set[str]: Forgotten item strings (non-comment, whitespace-stripped).
    """
    path = data_dir / "ignored_items.txt"
    if not path.is_file():
        return set()
    result = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            result.add(line)
    return result


def _read_progress(path) -> dict:
    """Read list_action_progress.json. Returns defaults if missing/corrupt."""
    import json as _json
    if not path.is_file():
        return {"unmatched": 0, "wool": 0, "coles": 0}
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ("unmatched", "wool", "coles"):
                data.setdefault(key, 0)
            return data
    except (ValueError, OSError):
        pass
    return {"unmatched": 0, "wool": 0, "coles": 0}


def _write_progress(path, progress: dict) -> None:
    """Write progress JSON atomically (temp + rename)."""
    import json as _json
    import tempfile as _tf
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = _tf.mkstemp(suffix=".json", prefix="progress_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            _json.dump(progress, fh, indent=2)
        os.replace(tmp, str(path))
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _parse_unmatched_item(line: str) -> tuple[str, str]:
    """Parse an unmatched.txt line 'ProductName [store]' -> (name, store).

    Args:
        line: e.g. "Milk 2L [woolworths]".

    Returns:
        (product_name, store). store is "" if no [store] suffix.
    """
    import re as _re
    m = _re.match(r"^(.+?)\s*\[(\w+)\]$", line)
    if m:
        return m.group(1).strip(), m.group(2).strip().lower()
    return line.strip(), ""


def _prompt_action(options: str) -> str:
    """Prompt the user for an action. Returns the lowercased input.

    Args:
        options: hint text shown in the prompt, e.g. "[a]dd [s]kip [stop] [done]".
    """
    try:
        return input(f"\n{options} > ").strip().lower()
    except EOFError:
        return "stop"


def _map_status(data_dir, progress_path) -> int:
    """Show progress across all 3 lists (X/Y resolved per list)."""
    progress = _read_progress(progress_path)
    lines = [header("Map Status", "📊")]
    for key in ("unmatched", "wool", "coles"):
        fname = _LIST_FILES[key]
        items = _read_list_file(data_dir / fname)
        idx = progress.get(key, 0)
        total = len(items)
        remaining = max(0, total - idx)
        done = min(idx, total)
        lines.append(
            kv(key, f"{done}/{total} resolved · {remaining} remaining")
        )
    print("\n".join(lines))
    return 0


def _map_unmatched_item(engine, item: str) -> str:
    """Resolve one unmatched item via the lookup chain (interactive).

    Returns: "advance" | "stop" | "done".
    """
    from core.lookup import LookupStatus

    name, store = _parse_unmatched_item(item)
    print(f"\n  Looking up: {name}" + (f" [{store}]" if store else ""))

    try:
        result = engine.find_product(name, interactive=True)
    except Exception as exc:
        print(f"  Error: {exc}")
        return _prompt_action("[s]kip [stop] [done]")

    if result.status == LookupStatus.EXACT_SHEET:
        prices_str = _format_prices(
            result.prices, result.brand, result.generic_name
        )
        print(f"  Found (exact): {result.generic_name}")
        print(f"  Prices: {prices_str}")
        return _prompt_action("[s]kip [stop] [done]")

    if result.status == LookupStatus.KEYWORD_ALIAS:
        prices_str = _format_prices(
            result.prices, result.brand, result.generic_name
        )
        print(f"  Found (alias): {result.generic_name}")
        print(f"  Prices: {prices_str}")
        return _prompt_action("[s]kip [stop] [done]")

    if result.status == LookupStatus.CANDIDATES:
        print("  Which did you mean?")
        for i, c in enumerate(result.candidates, 1):
            brand = f" ({c.brand})" if c.brand else ""
            print(f"    {i}) {c.generic_name}{brand}"
                  f"{unit_suffix(getattr(c, 'size', '') or '')} "
                  f"[score {c.score}]")
        action = _prompt_action("[number] [s]kip [stop] [done]")
        if action.isdigit():
            pick = int(action)
            if 1 <= pick <= len(result.candidates):
                chosen = result.candidates[pick - 1]
                try:
                    res = engine.persist_alias(name, chosen.row_index)
                    if res.get("wrote"):
                        print(ok(f"Alias '{name}' -> '{chosen.generic_name}' "
                                 f"(row {chosen.row_index})"))
                    else:
                        print(f"  Alias not written: {res.get('error', 'unknown')}")
                except Exception as exc:
                    print(f"  persist_alias failed: {exc}")
            else:
                print(f"  Invalid pick {pick}")
        elif action in ("s", "skip", "next"):
            return "advance"
        elif action == "stop":
            return "stop"
        elif action == "done":
            return "done"
        return _prompt_action("[s]kip [stop] [done]")

    if result.status == LookupStatus.LIVE_SEARCH:
        prices_str = _format_prices(
            result.prices, result.brand, result.generic_name
        )
        print(f"  Live search found: {result.generic_name}")
        print(f"  Prices: {prices_str}")
        for item_live in result.live_items[:5]:
            spec = f" [{item_live.special_desc}]" if item_live.is_special else ""
            disp = _product_price_display(item_live.store, item_live)
            print(f"    {item_live.store}: {item_live.raw_name} "
                  f"{disp}{spec}")
        action = _prompt_action("[a]dd [s]kip [stop] [done]")
        if action in ("a", "add"):
            _add_from_live_search(result, name)
            return _prompt_action("[s]kip [stop] [done]")
        elif action in ("s", "skip", "next"):
            return "advance"
        elif action == "stop":
            return "stop"
        elif action == "done":
            return "done"
        return _prompt_action("[s]kip [stop] [done]")

    # NOT_FOUND
    print(f"  Not found in sheet or either store.")
    return _prompt_action("[s]kip [stop] [done]")


def _search_store_with_fallback(store: str, query: str, page_size: int = 5):
    """Search a store with progressive query simplification.

    Stores use different product names and the sheet's Col A often includes
    size tokens (e.g. "Steggles Habanero Wings 1Kg") that cause exact-match
    failures on the store's search API. This tries progressively simpler
    queries until one returns results:

    1. Full query as-is ("Steggles Habanero Wings 1Kg")
    2. Size tokens stripped ("Steggles Habanero Wings")
    3. First 3 tokens only ("Steggles Habanero Wings")

    Args:
        store (str): "woolworths" or "coles".
        query (str): The product name to search (typically Col A value).
        page_size (int): Max results per query.

    Returns:
        tuple[list, str]: (results, query_that_worked). Results is [] if all
        attempts returned empty. query_that_worked is the query that yielded
        results (or the original query if none did).
    """
    from core.name_matcher import _SIZE_PATTERN
    import re

    if store == "woolworths":
        from extractors.woolworths_extractor import fetch_woolworths_search_noauth
        fetcher = fetch_woolworths_search_noauth
    else:
        from extractors.coles_extractor import fetch_coles_search
        fetcher = fetch_coles_search

    # Build progressive query list: full → size-stripped → first 3 tokens.
    queries = [query]
    stripped = _SIZE_PATTERN.sub("", query)
    stripped = re.sub(r"\s+", " ", stripped).strip(" ,-")
    if stripped and stripped.lower() != query.lower():
        queries.append(stripped)
    tokens = query.split()
    if len(tokens) > 3:
        short = " ".join(tokens[:3])
        if short.lower() not in [q.lower() for q in queries]:
            queries.append(short)

    for q in queries:
        try:
            results = fetcher(q, page_size=page_size)
            if results:
                return results, q
        except Exception:
            continue
    return [], query


def _queue_add_to_list(store: str, generic_name: str, keyword: str,
                       size: str = "") -> None:
    """Queue one wool/coles 'add' item on add_to_list (dup-guarded).

    Called ONLY after a successful update_single_price in the wool/coles
    add flow. Prints the confirmation or already-there line; never raises
    (a queue write failure must not fail a price write that already
    happened) — it prints an error line instead.

    Args:
        store (str): "woolworths" or "coles".
        generic_name (str): the Col A generic name (stable dup key).
        keyword (str): the live-search result-0 exact store product name.
        size (str): Rule B resolved unit (stored on the queue entry).
    """
    from core import add_to_list as atl
    try:
        result = atl.add_entry(store, keyword, generic_name, size=size)
    except (OSError, ValueError) as exc:
        print(f"add_to_list write failed: {exc}")
        return
    entry = result["entry"]
    if result["added"]:
        print(ok(f"Added to add_to_list: {entry['keyword']}"))
    else:
        print(f"Already on add_to_list (since {atl.since_label(entry)}): "
              f"{entry['keyword']} — not added again")


def _map_store_item(list_name: str, item: str) -> str:
    """Resolve one wool/coles missing item via live search (interactive).

    Args:
        list_name: "wool" or "coles".
        item: the generic name (Col A value from the sheet).

    Returns: "advance" | "stop" | "done".
    """
    store = "woolworths" if list_name == "wool" else "coles"
    print(f"\n  Looking up {store}: {item}")

    results, query_used = _search_store_with_fallback(store, item, page_size=5)
    if query_used != item:
        print(f"  (matched on simplified query: '{query_used}')")

    if not results:
        print(f"  No {store} results found.")
        return _prompt_action("[a]dd [na] [keyword] [s]kip [stop] [done]")

    print(f"  {store.capitalize()} results:")
    for i, prod in enumerate(results[:5], 1):
        spec = f" [{prod.special_desc}]" if prod.is_special else ""
        disp = _product_price_display(store, prod)
        print(f"    {i}) {prod.raw_name} {disp}{spec}")

    action = _prompt_action("[a]dd [s]kip [stop] [done]")
    if action in ("a", "add"):
        # Update the price for this generic name in the sheet
        from core.sheets_sync import update_single_price
        best = results[0]
        # Rule B: resolve the unit (live size -> name parse -> ask).
        try:
            unit = _resolve_add_unit(
                best.raw_name, getattr(best, "size", "") or "")
        except ValueError as exc:
            print(f"  {exc}")
            return _prompt_action(
                "[a]dd [na] [keyword] [s]kip [stop] [done]")
        try:
            res = update_single_price(item, store, best.price, size=unit)
            if res.get("found"):
                print(ok(f"Updated {store} price for '{item}' "
                         f"(row {res.get('row_index')}): ${best.price:.2f}"))
                _queue_add_to_list(store, item, best.raw_name, size=unit)
            else:
                print(f"  Could not find '{item}' in sheet: "
                      f"{res.get('error', 'unknown')}")
        except Exception as exc:
            print(f"  update_single_price failed: {exc}")
        return _prompt_action("[s]kip [stop] [done]")
    elif action in ("s", "skip", "next"):
        return "advance"
    elif action == "stop":
        return "stop"
    elif action == "done":
        return "done"
    return _prompt_action("[s]kip [stop] [done]")


def _add_from_live_search(result, original_query: str,
                          unit_override: str = "") -> bool:
    """Explicit add of a live-search result to the sheet + Queue 2.

    Picks the first live item with a price > 0 (the ranked choice where a
    gated pair exists — see lookup Step 5). Writes via
    sheets_sync.add_product_row with the query as a Col P alias and
    store_keyword EMPTY (interpretation 0.4 — the item is not on any
    store shopping list yet). After a successful write the item is
    queued on searched_items so the Wednesday live window adds it to
    the store website list (spec §3.4; never automatic elsewhere).

    Returns:
        bool — True when the row was written and queued; False on any
        failure (error already printed).
    """
    from core.sheets_sync import add_product_row

    best = None
    for item in result.live_items:
        if item.price and item.price > 0:
            best = item
            break
    if best is None:
        print("  No live result with a price to add.")
        return False

    # Use the live result's store for the price column
    store = best.store.lower()
    # Rule B: resolve the unit BEFORE the write (B2). Non-interactive
    # callers pass unit_override (--unit); interactive sessions ask.
    try:
        unit = _resolve_add_unit(
            best.raw_name, getattr(best, "size", "") or "",
            override=unit_override)
    except ValueError as exc:
        print(f"  {exc} — re-run with --unit \"1L\" or "
              f"--unit \"unit unavailable\"")
        return False
    try:
        res = add_product_row(
            generic_name=best.raw_name,
            store=store,
            price=best.price,
            brand=best.brand,
            size=unit,
            category=best.category,
            store_keyword="",
            alias=original_query,
            is_special=best.is_special,
            special_desc=best.special_desc,
        )
        if res.get("wrote"):
            print(ok(f"Added '{best.raw_name}' to sheet "
                     f"(row {res.get('row_index')}, {store} ${best.price:.2f})"))
            print(ok(f"Alias '{original_query}' saved to Col P."))
            # Queue 2 hook (explicit-add route only).
            _queue_searched_item(
                store, best.raw_name, best.raw_name,
                store_product_id=getattr(best, "product_id", "") or "",
                size=unit)
            return True
        else:
            print(f"  Add failed: {res.get('error', 'unknown')}")
    except Exception as exc:
        print(f"  add_product_row failed: {exc}")
    return False


def _product_price_display(store: str, prod) -> str:
    """Price token for one live-search product line.

    Woolworths prices get the always-on display discount (compounded
    extra 5% for home brands classified via the item's own brand/name);
    every other store shows the raw price.

    Args:
        store: store id of the product ("woolworths"/"coles"/...).
        prod: duck-typed product exposing .price, .raw_name, .brand.

    Returns:
        Formatted price string including the raw price reference.
    """
    from core.woolworths_discounts import (
        format_discounted_price,
        is_woolworths_home_brand,
    )
    if (store or "").lower() == "woolworths":
        return format_discounted_price(
            prod.price,
            is_woolworths_home_brand(
                prod.raw_name, getattr(prod, "brand", "")
            ),
        )
    return f"${prod.price:.2f}"


def _format_prices(prices: dict, brand: str = "", name: str = "") -> str:
    """Format a prices dict as 'coles: $Y.YY, woolworths: <discounted>'."""
    if not prices:
        return "no prices"
    from core.woolworths_discounts import (
        format_discounted_price,
        is_woolworths_home_brand,
    )
    parts = []
    for store in sorted(prices.keys()):
        p = prices[store]
        if store == "woolworths":
            is_home = is_woolworths_home_brand(name, brand)
            parts.append(
                f"woolworths: {format_discounted_price(p, is_home)}"
            )
        else:
            parts.append(f"{store}: ${p:.2f}")
    return ", ".join(parts)


def _cmd_map(args) -> int:
    """Interactive one-item-at-a-time list resolution.

    Usage:
        map unmatched  — resolve unmatched items via the lookup chain
        map wool      — live-search Woolworths for rows missing a Woolies price
        map coles     — live-search Coles for rows missing a Coles price
        map status    — show progress across all 3 lists
    """
    data_dir = _TRACKER / "data"
    progress_path = data_dir / "list_action_progress.json"

    if args.list_name == "status":
        return _map_status(data_dir, progress_path)

    list_name = args.list_name
    list_file = data_dir / _LIST_FILES[list_name]
    if not list_file.is_file():
        print(f"Error: {list_file.name} not found in {data_dir}", file=sys.stderr)
        return 1

    items = _read_list_file(list_file)
    if not items:
        print(f"No items in {list_file.name}.")
        return 0

    progress = _read_progress(progress_path)
    idx = progress.get(list_name, 0)

    if idx >= len(items):
        print(f"All {len(items)} items in {list_name} already resolved.")
        return 0

    # Non-interactive mode (for LLM/skill use via subprocess): one action per
    # invocation, no blocking input(). Triggered by any --next/--pick/--add/
    # --skip flag, or automatically when stdin is not a TTY (subprocess context).
    has_action = (args.pick is not None or args.add or args.skip or args.next
                  or args.na or args.forget or args.keyword is not None)
    try:
        is_tty = sys.stdin.isatty()
    except (ValueError, OSError):
        is_tty = False
    if has_action or not is_tty:
        return _cmd_map_noninteractive(
            args, list_name, items, idx, progress, progress_path, data_dir)

    _load_env()

    print(header(f"Map {list_name}", "📋"))
    print(f"({len(items)} items, resuming at #{idx + 1})")
    print("✳️ Commands during session: number (pick candidate), "
          "add, forget (unmatched) / na (wool/coles), skip/next, stop, done")

    engine = None
    if list_name == "unmatched":
        from core.lookup import LookupEngine
        engine = LookupEngine()

    while idx < len(items):
        item = items[idx]
        print(f"\n--- Item {idx + 1}/{len(items)} ---")

        try:
            if list_name == "unmatched":
                action = _map_unmatched_item(engine, item)
            else:
                action = _map_store_item(list_name, item)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            action = "stop"

        if action == "stop":
            progress[list_name] = idx + 1
            _write_progress(progress_path, progress)
            print(f"\nPaused at item #{idx + 2}/{len(items)}.")
            print(f"Resume with: map {list_name}")
            return 0
        elif action == "done":
            progress[list_name] = idx + 1
            _write_progress(progress_path, progress)
            print(f"\nSession ended at item #{idx + 2}/{len(items)}.")
            return 0

        idx += 1

    progress[list_name] = idx
    _write_progress(progress_path, progress)
    print(f"\nAll {len(items)} items in '{list_name}' resolved!")
    return 0


# ============================================================================
# Non-interactive map (one action per invocation — for LLM/skill subprocess use)
# ============================================================================

def _resolve_and_print_unmatched(engine, item: str):
    """Resolve one unmatched item and print the result without prompting.

    Non-interactive variant of _map_unmatched_item: same lookup chain
    (Steps 1->2->3->5) and same output, but returns instead of calling
    input(). Used by --next and the advance-and-show helpers.

    Args:
        engine: A core.lookup.LookupEngine instance.
        item (str): One line from unmatched.txt.

    Returns:
        tuple: (result, status) where result is the LookupResult (or None on
        error) and status is the LookupStatus (or None on error).
    """
    from core.lookup import LookupStatus

    name, store = _parse_unmatched_item(item)
    print(f"\n  Looking up: {name}" + (f" [{store}]" if store else ""))

    try:
        result = engine.find_product(name, interactive=True)
    except Exception as exc:
        print(f"  Error: {exc}")
        return None, None

    status = result.status
    if status in (LookupStatus.EXACT_SHEET, LookupStatus.KEYWORD_ALIAS):
        label = "exact" if status == LookupStatus.EXACT_SHEET else "alias"
        print(f"  Found ({label}): {result.generic_name}")
        print(
            f"  Prices: {_format_prices(result.prices, result.brand, result.generic_name)}"
        )
    elif status == LookupStatus.CANDIDATES:
        print("  Which did you mean?")
        for i, c in enumerate(result.candidates or [], 1):
            brand = f" ({c.brand})" if c.brand else ""
            print(f"    {i}) {c.generic_name}{brand}"
                  f"{unit_suffix(getattr(c, 'size', '') or '')} "
                  f"[score {c.score}]")
    elif status == LookupStatus.LIVE_SEARCH:
        print(f"  Live search found: {result.generic_name}")
        print(
            f"  Prices: {_format_prices(result.prices, result.brand, result.generic_name)}"
        )
        for li in (result.live_items or [])[:5]:
            spec = f" [{li.special_desc}]" if li.is_special else ""
            disp = _product_price_display(li.store, li)
            print(f"    {li.store}: {li.raw_name} {disp}{spec}")
    else:
        print(f"  Not found in sheet or either store.")

    return result, status


def _resolve_and_print_store(list_name: str, item: str):
    """Live-search one store for one item and print results without prompting.

    Non-interactive variant of _map_store_item: same store search and output,
    but returns the results list instead of calling input().

    Args:
        list_name (str): "wool" or "coles".
        item (str): The generic name (Col A value from the sheet).

    Returns:
        list: Search results (may be empty on failure/no results).
    """
    store = "woolworths" if list_name == "wool" else "coles"
    print(f"\n  Looking up {store}: {item}")

    results, query_used = _search_store_with_fallback(store, item, page_size=5)
    if query_used != item:
        print(f"  (matched on simplified query: '{query_used}')")

    if not results:
        print(f"  No {store} results found. Use --keyword NAME or --skip.")
        return []

    print(f"  {store.capitalize()} results:")
    for i, prod in enumerate(results[:5], 1):
        spec = f" [{prod.special_desc}]" if prod.is_special else ""
        disp = _product_price_display(store, prod)
        print(f"    {i}) {prod.raw_name} {disp}{spec}")

    return results


def _advance_and_show(list_name, items, idx, progress, progress_path, data_dir):
    """Advance progress, then resolve and show the next item (or 'all done').

    Persists the new index BEFORE resolving the next item so a crash never
    loses the resume position. After advancing, resolves and prints the next
    item using the same non-interactive resolver (--next style).

    Args:
        list_name (str): "unmatched", "wool", or "coles".
        items (list[str]): Full list of items.
        idx (int): The index that was just resolved (0-based).
        progress (dict): Progress dict (mutated + persisted).
        progress_path (Path): Path to list_action_progress.json.
        data_dir (Path): grocery-price-tracker/data/ directory.

    Returns:
        int: 0 on success.
    """
    progress[list_name] = idx + 1
    _write_progress(progress_path, progress)

    next_idx = idx + 1
    if next_idx >= len(items):
        print(f"\nAll {len(items)} items in '{list_name}' resolved!")
        return 0

    print(f"\n--- Item {next_idx + 1}/{len(items)} ---")
    item = items[next_idx]
    if list_name == "unmatched":
        from core.lookup import LookupEngine
        _resolve_and_print_unmatched(LookupEngine(), item)
    else:
        _resolve_and_print_store(list_name, item)

    if list_name == "unmatched":
        print("\n✳️ Next: --pick N / --add / --forget / --skip / (stop)")
    else:
        print("\n✳️ Next: --add / --na / --keyword NAME / --skip / (stop)")
    return 0


def _cmd_map_noninteractive(args, list_name, items, idx,
                            progress, progress_path, data_dir):
    """Non-interactive map: one action per invocation (for LLM/skill subprocess).

    Designed so OpenClaw's LLM can drive the one-item-at-a-time flow via the
    grocery-price SKILL: each Telegram message triggers exactly one CLI call
    with a single action flag. No blocking input().

    Actions:
        --next (default): Resolve and show current item, DON'T advance.
        --pick N: Re-resolve, pick candidate N, persist alias to Col P,
                  advance, show next item.
        --add: Re-resolve, add new row (unmatched live search) or update price
               (wool/coles), advance, show next item.
        --skip: Skip current item, advance, show next item.

    Args:
        args: Parsed argparse Namespace (--pick/--add/--skip/--next).
        list_name (str): "unmatched", "wool", or "coles".
        items (list[str]): Full list of items.
        idx (int): Current resume index (0-based).
        progress (dict): Progress dict.
        progress_path (Path): Path to list_action_progress.json.
        data_dir (Path): grocery-price-tracker/data/ directory.

    Returns:
        int: 0 on success, 1 on error.
    """
    _load_env()
    item = items[idx]

    # --skip: advance without resolving.
    if args.skip:
        name = _parse_unmatched_item(item)[0] if list_name == "unmatched" else item
        print(ok(f"Skipped: {name}"))
        return _advance_and_show(
            list_name, items, idx, progress, progress_path, data_dir)

    # --forget: unmatched only — append to ignored_items.txt so the item is
    # permanently excluded from future unmatched lists (Phase 9.6).
    if args.forget:
        if list_name != "unmatched":
            print("Error: --forget only valid for 'unmatched' list.",
                  file=sys.stderr)
            return 1
        ignored_path = data_dir / "ignored_items.txt"
        try:
            with ignored_path.open("a", encoding="utf-8") as f:
                f.write(item + "\n")
            print(ok(f"Forgotten: {item} "
                     f"(excluded from future unmatched lists)"))
        except OSError as exc:
            print(f"forget failed: {exc}", file=sys.stderr)
            return 1
        return _advance_and_show(
            list_name, items, idx, progress, progress_path, data_dir)

    # --na: wool/coles only — write "NA" to the store keyword col (I/J) and
    # price col (D/E) so the row is permanently excluded from the missing list
    # (Phase 9.6).
    if args.na:
        if list_name == "unmatched":
            print("Error: --na only valid for 'wool'/'coles' lists.",
                  file=sys.stderr)
            return 1
        store = "woolworths" if list_name == "wool" else "coles"
        from core.sheets_sync import mark_not_available
        try:
            res = mark_not_available(item, store)
        except Exception as exc:
            print(f"mark_not_available failed: {exc}", file=sys.stderr)
            return 1
        if res.get("found"):
            print(ok(f"Marked '{item}' as NA at {store} "
                     f"(row {res.get('row_index')})"))
        else:
            print(f"Could not find '{item}' in sheet: "
                  f"{res.get('error', 'unknown')}", file=sys.stderr)
            return 1
        return _advance_and_show(
            list_name, items, idx, progress, progress_path, data_dir)

    # --keyword: wool/coles only — save user-provided store name as keyword
    # col (I/J) when live search returned nothing (Phase 9.6 plain-english).
    if args.keyword is not None:
        if list_name == "unmatched":
            print("Error: --keyword only valid for 'wool'/'coles' lists.",
                  file=sys.stderr)
            return 1
        store = "woolworths" if list_name == "wool" else "coles"
        from core.sheets_sync import set_store_keyword
        try:
            res = set_store_keyword(item, store, args.keyword)
        except Exception as exc:
            print(f"set_store_keyword failed: {exc}", file=sys.stderr)
            return 1
        if res.get("found"):
            print(ok(f"Saved '{args.keyword}' as {store} keyword "
                     f"(row {res.get('row_index')})"))
        else:
            print(f"Could not find '{item}' in sheet: "
                  f"{res.get('error', 'unknown')}", file=sys.stderr)
            return 1
        return _advance_and_show(
            list_name, items, idx, progress, progress_path, data_dir)

    # --pick N: re-resolve current item, pick candidate N, persist, advance.
    if args.pick is not None:
        if list_name != "unmatched":
            print("Error: --pick only valid for 'unmatched' list.", file=sys.stderr)
            return 1
        from core.lookup import LookupEngine, LookupStatus

        name, _store = _parse_unmatched_item(item)
        print(f"--- Item {idx + 1}/{len(items)} ---")
        try:
            result = engine_result = LookupEngine().find_product(
                name, interactive=True)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if result.status != LookupStatus.CANDIDATES:
            print(f"No candidates for this item (status: {result.status}). "
                  f"Use --skip or --add.")
            return 1

        cands = result.candidates or []
        if not (1 <= args.pick <= len(cands)):
            print(f"Invalid pick {args.pick} (1-{len(cands)} available).")
            return 1

        chosen = cands[args.pick - 1]
        try:
            res = LookupEngine().persist_alias(name, chosen.row_index)
            if res.get("wrote"):
                print(ok(f"Alias '{name}' -> '{chosen.generic_name}' "
                         f"(row {chosen.row_index})"))
            else:
                print(f"Alias not written: {res.get('error', 'unknown')}")
        except Exception as exc:
            print(f"persist_alias failed: {exc}")

        return _advance_and_show(
            list_name, items, idx, progress, progress_path, data_dir)

    # --add: re-resolve current item, add/update from result, advance.
    if args.add:
        print(f"--- Item {idx + 1}/{len(items)} ---")
        if list_name == "unmatched":
            from core.lookup import LookupEngine, LookupStatus

            name, _store = _parse_unmatched_item(item)
            engine = LookupEngine()
            try:
                result = engine.find_product(name, interactive=True)
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1

            if result.status != LookupStatus.LIVE_SEARCH:
                # Force a live search for CANDIDATES/NOT_FOUND items so the
                # user can still add the product as a new row. Fixes the
                # "--add does nothing" dead-end when a bad partial candidate
                # blocked Step 5 from running.
                live_items = engine._live_search(name)
                if not live_items:
                    print(f"No live search results found for '{name}'. "
                          f"Use --skip or --forget.")
                    return 1
                from dataclasses import replace as _replace
                result = _replace(result, live_items=live_items)

            if not _add_from_live_search(
                    result, name,
                    unit_override=getattr(args, "unit", None) or ""):
                return 1
        else:
            store = "woolworths" if list_name == "wool" else "coles"
            results, query_used = _search_store_with_fallback(
                store, item, page_size=5)
            if query_used != item:
                print(f"  (matched on simplified query: '{query_used}')")

            if not results:
                print(f"No {store} results found. Use --keyword NAME or --skip.")
                return 1

            best = results[0]
            # Rule B: resolve the unit (--unit -> live size -> name
            # parse -> fail-fast; interactive sessions ask instead).
            try:
                unit = _resolve_add_unit(
                    best.raw_name,
                    getattr(best, "size", "") or "",
                    override=getattr(args, "unit", None) or "")
            except ValueError as exc:
                print(f"Error: {exc} — re-run with --unit \"1L\" or "
                      f"--unit \"unit unavailable\"", file=sys.stderr)
                return 1
            from core.sheets_sync import update_single_price
            try:
                res = update_single_price(
                    item, store, best.price,
                    is_special=best.is_special,
                    special_desc=best.special_desc,
                    size=unit)
                if res.get("found"):
                    print(ok(f"Updated {store} price for '{item}' "
                             f"(row {res.get('row_index')}): ${best.price:.2f}"))
                    _queue_add_to_list(store, item, best.raw_name,
                                       size=unit)
                else:
                    print(f"Could not find '{item}' in sheet: "
                          f"{res.get('error', 'unknown')}")
            except Exception as exc:
                print(f"update_single_price failed: {exc}")

        return _advance_and_show(
            list_name, items, idx, progress, progress_path, data_dir)

    # --next (default when no action flag): resolve and show current item.
    print(f"--- Item {idx + 1}/{len(items)} ---")
    if list_name == "unmatched":
        from core.lookup import LookupEngine
        _resolve_and_print_unmatched(LookupEngine(), item)
    else:
        _resolve_and_print_store(list_name, item)

    if list_name == "unmatched":
        print("\n✳️ Next: --pick N / --add / --forget / --skip / (stop)")
    else:
        print("\n✳️ Next: --add / --na / --keyword NAME / --skip / (stop)")
    return 0


# ============================================================================
# Handler: _cmd_add_to_list — manual website-add queue (show / done)
# ============================================================================

def _cmd_add_to_list(args) -> int:
    """Manual website-add queue: show pending items / mark items done.

    Offline-safe: no _load_env(), no sheet access, no live search (like
    `unmapped`). The queue file (data/add_to_list.json) is fed ONLY by the
    wool/coles map 'add' flows and drained ONLY here.

    Behavior:
        show: print the pending queue (Coles section first, then
              Woolworths, continuous numbering); exit 0.
        done: remove the given item numbers (all-or-nothing), print one
              line per removed entry, then re-print the remainder; errors
              (missing --items, unparsable items, empty queue, out of
              range) go to stderr with exit 1 and never mutate the file.

    Args:
        args: Parsed argparse Namespace (action, items).

    Returns:
        int: 0 on success, 1 on error.
    """
    from core import add_to_list as atl

    if args.action == "show":
        print(atl.render_show())
        return 0

    # done
    raw_items = getattr(args, "items", None)
    if not raw_items:
        print("Error: 'add-to-list done' requires --items "
              "(e.g. --items \"1,2,3\").", file=sys.stderr)
        return 1
    try:
        numbers = atl.parse_items_arg(raw_items)
    except ValueError:
        print(f"Error: could not parse items '{raw_items}' "
              f"— use numbers like \"1,2,3\".", file=sys.stderr)
        return 1
    try:
        result = atl.remove_by_numbers(numbers)
    except ValueError as exc:
        # Empty queue / out of range — message already names the valid
        # range; all-or-nothing means the file is untouched.
        print(exc, file=sys.stderr)
        return 1
    for entry in result["removed"]:
        store = str(entry.get("store", "")).strip().capitalize()
        print(ok(f"Removed: {entry.get('keyword', '')} ({store})"))
    if result["remaining_count"] > 0:
        print(f"{result['remaining_count']} still pending:")
        print(atl.render_remaining_flat(atl.ordered_entries()))
    else:
        print(atl.render_remaining_flat([]))
    return 0


# ============================================================================
# Handler: _cmd_searched_items — explicit-add Wednesday queue (show/remove/clear)
# ============================================================================

def _cmd_searched_items(args) -> int:
    """Searched-items queue management: show / remove CODE,CODE / clear.

    Offline-safe: no _load_env(), no sheet access, no live search (mirrors
    `add-to-list`). The queue (data/searched_items.json) is fed ONLY by
    explicit adds (`search --add-item N` and the `map --add` unmatched
    live route) and drained ONLY by the Wednesday live flush.

    Behavior:
        show:   print the pending queue (Coles first, then Woolworths) as
                "store · exact product name · size · [CODE]"; exit 0.
        remove: remove the given codes (all-or-nothing, case-insensitive);
                unknown code -> self-correcting error on stderr, exit 1,
                file untouched; prints the remainder.
        clear:  empty the queue and tombstone every code; prints what it
                cleared (SKILL.md confirm-before-mutate applies).

    Args:
        args: Parsed argparse Namespace (action, items).

    Returns:
        int: 0 on success, 1 on error.
    """
    from core import searched_items as si

    if args.action == "show":
        print(si.render_show())
        if si.ordered_entries():
            print("💬 'show searched items' any time to review the queue.")
        return 0

    if args.action == "remove":
        raw_items = getattr(args, "items", None)
        if not raw_items:
            print("Error: 'searched-items remove' requires --items "
                  "(e.g. --items \"KAT,RUM\").", file=sys.stderr)
            return 1
        try:
            codes = si.parse_codes_arg(raw_items)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        try:
            result = si.remove_by_codes(codes)
        except ValueError as exc:
            # Unknown code / empty queue — exact self-correcting message;
            # all-or-nothing means the file is untouched.
            print(exc, file=sys.stderr)
            return 1
        for entry in result["removed"]:
            store = str(entry.get("store", "")).strip().capitalize()
            print(ok(f"Removed: {entry.get('keyword', '')} ({store}) "
                     f"[{entry.get('code', '')}]"))
        if result["remaining_count"] > 0:
            print(f"{result['remaining_count']} still pending:")
            print(si.render_show())
        else:
            print(si.render_show())
        print("💬 'show searched items' any time to review the queue.")
        return 0

    # clear
    result = si.clear_all()
    removed = result["removed"]
    if not removed:
        print(si.render_show())
        return 0
    print(ok(f"Cleared {len(removed)} item(s) from searched_items "
             f"(codes tombstoned for "
             f"{si.TOMBSTONE_TTL_DAYS} days):"))
    for entry in removed:
        store = str(entry.get("store", "")).strip().capitalize()
        print(f"  - {entry.get('keyword', '')} ({store}) "
              f"[{entry.get('code', '')}]")
    print(si.render_show())
    return 0


# ============================================================================
# Handler: _cmd_backfill_keywords — one-time Col P (Keywords) backfill (9.9)
# ============================================================================

# Column indices in Products_Master (0-based) for the backfill.
_SIZE_COL_BF = 2        # C (size — the unit column)
_KEYWORDS_COL = 15      # P (Keywords — user-query aliases)
_BRAND_TYPE_COL = 7     # H (Brand_Type)
_BRANDED_FLAG = "brand"  # Col H value that flags a branded row


def _derive_keyword_alias(name: str, brand_type: str = "") -> str:
    """Derive a Col P alias from a Col A product name (Phase 9.9 rule).

    Lowercase + whitespace-collapse via ``KeywordIndex._normalize`` (the exact
    form the matcher tokenizes against — no normalization mismatch), strip
    size/quantity tokens (``500ml``, ``1kg``, ``pack of 6``, ``x12``) via
    ``name_matcher._SIZE_PATTERN``, strip the leading brand token when Col H
    flags the row as ``brand``, then collapse to 2-4 significant tokens.

    Args:
        name (str): Col A product name.
        brand_type (str): Col H Brand_Type value ("" when absent).

    Returns:
        str: The derived alias (may be < 2 tokens if the name is short;
        "" only when the name itself is blank).
    """
    from core.name_matcher import KeywordIndex, _SIZE_PATTERN

    normalized = KeywordIndex._normalize(name)
    normalized = _SIZE_PATTERN.sub("", normalized)
    # Re-collapse whitespace left behind by the size-token strip.
    normalized = KeywordIndex._normalize(normalized)
    tokens = [t for t in normalized.split(" ") if t]
    # Strip the brand prefix only when Col H flags the row as branded.
    if KeywordIndex._normalize(brand_type) == _BRANDED_FLAG and len(tokens) > 2:
        tokens = tokens[1:]
    # Collapse to 2-4 significant tokens.
    tokens = tokens[:4]
    return " ".join(tokens)


def _cmd_backfill_keywords(args) -> int:
    """One-time Col P (Keywords) backfill derived from Col A (Phase 9.9).

    Reads Products_Master, derives an alias per row, and writes ONLY empty
    Col P cells in ONE batched update (``--overwrite`` forces a clobber of
    non-empty cells; OFF by default). Never touches Col I/J/K — those are
    per-store search keywords populated by the Wednesday Word-doc sync (9.4).
    """
    _load_env()
    from core.sheets_client import connect_worksheet

    ws = connect_worksheet()
    all_values = ws.get_all_values()
    rows = all_values[1:] if len(all_values) > 1 else []

    planned = []  # (row_index_1based, generic_name, existing_alias, new_alias)
    skipped_existing = 0
    skipped_blank = 0
    for i, row in enumerate(rows):
        row_index = i + 2  # 1-based; row 1 is the header
        generic = row[0].strip() if len(row) > 0 else ""
        if not generic:
            skipped_blank += 1
            continue
        existing = (
            row[_KEYWORDS_COL].strip() if len(row) > _KEYWORDS_COL else ""
        )
        if existing and not args.overwrite:
            skipped_existing += 1
            continue
        brand_type = (
            row[_BRAND_TYPE_COL].strip() if len(row) > _BRAND_TYPE_COL else ""
        )
        alias = _derive_keyword_alias(generic, brand_type)
        if not alias:
            skipped_blank += 1
            continue
        planned.append((row_index, generic, existing, alias))

    print(header("Backfill Keywords (Col P)", "📋"))
    print()
    print(kv("Rows examined", str(len(rows))))
    print(kv("Planned writes", str(len(planned))))
    print(kv("Skipped (Col P already set)", str(skipped_existing)))
    print(kv("Skipped (blank name/alias)", str(skipped_blank)))
    print()
    for row_index, generic, existing, alias in planned:
        print(f"{row_index}. {truncate(generic, 30)} · "
              f"{existing or EM_DASH} → {alias}")

    if args.dry_run:
        print()
        print(warn("[DRY RUN] no sheet write"))
        return 0

    if not planned:
        print()
        print("Nothing to write.")
        return 0

    # ONE batched update for all planned Col P cells.
    ws.batch_update([
        {"range": f"P{row_index}", "values": [[alias]]}
        for row_index, _generic, _existing, alias in planned
    ])
    print()
    print(f"Wrote {len(planned)} Col P cell(s) in one batched update.")
    return 0


def _cmd_backfill_sizes(args) -> int:
    """One-time Col C (size) backfill parsed from Col A/I/J (spec §5.2).

    Fills ONLY blank Col C cells whose size is parseable via
    name_matcher._SIZE_PATTERN from Col A, then Col I, then Col J.
    Non-empty Col C cells are NEVER modified (Rule C.3); unparseable
    rows stay blank and display the note (D-U3 — no guessed sizes, no
    bulk marker write). ONE batched update for all planned cells.
    """
    _load_env()
    from core.sheets_client import connect_worksheet
    from core.name_matcher import _SIZE_PATTERN

    ws = connect_worksheet()
    all_values = ws.get_all_values()
    rows = all_values[1:] if len(all_values) > 1 else []

    planned = []          # (row_index_1based, generic, size)
    skipped_set = 0       # Col C already non-empty
    left_blank = 0        # blank Col C, nothing parseable
    for i, row in enumerate(rows):
        row_index = i + 2
        generic = row[0].strip() if len(row) > 0 else ""
        current = (row[_SIZE_COL_BF].strip()
                   if len(row) > _SIZE_COL_BF else "")
        if current:
            skipped_set += 1
            continue
        size = ""
        for col in (0, 8, 9):  # Col A, Col I, Col J
            if len(row) > col:
                m = _SIZE_PATTERN.search(row[col])
                if m:
                    size = m.group(1).strip()
                    break
        if generic and size:
            planned.append((row_index, generic, size))
        else:
            left_blank += 1

    print(header("Backfill Sizes (Col C)", "📋"))
    print()
    print(kv("Rows examined", str(len(rows))))
    print(kv("Planned writes", str(len(planned))))
    print(kv("Skipped (Col C already set)", str(skipped_set)))
    print(kv("Left blank (no parseable size)", str(left_blank)))
    print()
    for row_index, generic, size in planned:
        print(f"{row_index}. {truncate(generic, 30)} · {EM_DASH} → {size}")

    if args.dry_run:
        print()
        print(warn("[DRY RUN] no sheet write"))
        return 0
    if not planned:
        print()
        print("Nothing to write.")
        return 0
    ws.batch_update([
        {"range": f"C{row_index}", "values": [[size]]}
        for row_index, _generic, size in planned
    ])
    print()
    print(f"Wrote {len(planned)} Col C cell(s) in one batched update.")
    return 0


# ============================================================================
# Handler: _cmd_backfill_home_brands — Col G home-brand classifier backfill
# ============================================================================

def _cmd_backfill_home_brands(args) -> int:
    """One-time Col G (Brand_Type) classifier backfill.

    Writes the literal "Home" marker into Col G for rows classified as
    Woolworths home brands, so every display surface can trust Col G:

      * Col G empty AND leading Col A name matches the canonical list;
      * OR Col G non-empty AND its value matches the canonical list
        (e.g. "Macro", "Woolworths BBQ") — normalized to "Home";
      * Col G already "Home" -> skipped (idempotent re-runs).

    Default: only EMPTY Col G cells get the name-based write; rows whose
    Col G carries a NON-matching brand are skipped (never clobber user
    data without consent). ``--overwrite`` additionally overrides those
    non-matching cells when the Col A NAME matches (trust the name).

    All planned writes go out in ONE batch_update of single-cell ranges.
    """
    _load_env()
    from core.sheets_client import connect_worksheet
    from core.sheets_sync import _find_col
    from core.woolworths_discounts import is_woolworths_home_brand

    ws = connect_worksheet()
    all_values = ws.get_all_values()
    sheet_header = all_values[0] if all_values else []
    rows = all_values[1:] if len(all_values) > 1 else []

    brand_col = _find_col(sheet_header, "Brand")
    if brand_col is None:
        brand_col = _find_col(sheet_header, "Brand_Type")
    if brand_col is None:
        brand_col = 6  # positional Col G fallback

    def _cell(row, idx):
        return row[idx].strip() if len(row) > idx else ""

    planned = []          # (row_index_1based, generic, current)
    skipped_already = 0   # Col G already Home
    skipped_existing = 0  # non-empty non-matching Col G (default mode)
    skipped_blank = 0     # blank Col A

    for i, row in enumerate(rows):
        row_index = i + 2  # 1-based; row 1 is the header
        generic = _cell(row, 0)
        if not generic:
            skipped_blank += 1
            continue
        current = _cell(row, brand_col)
        if current.lower() == "home":
            skipped_already += 1
            continue

        cell_matches = bool(current) and is_woolworths_home_brand(
            "", current
        )
        name_matches = is_woolworths_home_brand(generic, "")

        if not current and name_matches:
            planned.append((row_index, generic, ""))
        elif cell_matches:
            planned.append((row_index, generic, current))
        elif current and name_matches and args.overwrite:
            planned.append((row_index, generic, current))
        elif current:
            skipped_existing += 1

    print(header("Backfill Home Brands (Col G)", "📋"))
    print()
    print(kv("Rows examined", str(len(rows))))
    print(kv("Planned writes", str(len(planned))))
    print(kv("Skipped (Col G already 'Home')", str(skipped_already)))
    print(kv("Skipped (non-matching Col G present)", str(skipped_existing)))
    print(kv("Skipped (blank product name)", str(skipped_blank)))
    if args.overwrite:
        print(kv("Mode", "--overwrite (name match overrides brand cell)"))
    print()
    for row_index, generic, current in planned:
        print(
            f"{row_index}. {truncate(generic, 30)} · "
            f"{current or EM_DASH} → Home"
        )

    if args.dry_run:
        print()
        print(warn("[DRY RUN] no sheet write"))
        return 0

    if not planned:
        print()
        print("Nothing to write.")
        return 0

    # ONE batched update for all planned Col G cells.
    ws.batch_update([
        {"range": f"G{row_index}", "values": [["Home"]]}
        for row_index, _generic, _current in planned
    ])
    print()
    print(f"Wrote {len(planned)} Col G cell(s) in one batched update.")
    return 0


# ============================================================================
# main() dispatcher
# ============================================================================

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
