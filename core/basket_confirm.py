#!/usr/bin/env python3
"""Pre-basket live-search confirmation flow (B2 add-on, user rules 2026-09-03).

`optimize` prices the basket from the SHEET first, then classifies
every item the sheet cannot fully price. The decision tree (user's
own wording, final version):

    1. Fully sheet-priced                        -> straight to basket.
    2. One store priced — the other side:
       a. KEYWORD missing -> already queued on   -> "already queued for
          searched / to-do list?                    Wednesday", no
          (queued means the pricing is on the       action, no write.
          sheet; queues carry no prices.)
       b. PRICING missing/error     -> closest substitute row ON THE
          SHEET first (used read-only, labelled
          "sub", never written) -> else live
          search. Price-only write into the
          existing row — UNLESS that side still
          has a stale keyword (price was
          "N/A <date>"): then the keyword is
          RE-SYNCED to the found product and the
          item goes on the TO-DO list so the
          user verifies the website shopping
          list (adding the right item there
          brings the row back to weekly
          refreshes). Either way the item stays
          visible via the to-do reminder.
    3. Row exists, NEITHER store priced          -> same as 2b for both
                                                      sides.
    4. NOT on the sheet at all                   -> live search; the
                                                      user chooses per
                                                      item: compare only
                                                      (nothing written)
                                                      or compare + add
                                                      (new row +
                                                      searched list).

Codes: 3 letters (same alphabet as the searched-items queue, separate
namespace — pending-state only). Nothing is written at plan time;
writes happen only on explicit `optimize --confirm`.

List semantics are untouched: this module only CALLS the established
writers (update_single_price / set_store_keyword / add_product_row /
searched_items.add_entry / add_to_list.add_entry) and only ever READS
the queues.
"""
from __future__ import annotations
import json
import os
import random
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.telegram_format import UNIT_UNAVAILABLE, header

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OPTIMIZE_PENDING_PATH = DATA_DIR / "optimize_pending.json"  # patchable

# Same alphabet as the searched-items queue (A-Z minus I/O), but the
# pending namespace is separate: codes live only in optimize_pending.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 3

GROUP_LABELS = {
    "A": "Coles pricing missing",
    "B": "Woolworths pricing missing",
    "C": "No pricing at all",
}


# ---------------------------------------------------------------------------
# Pending-state IO (atomic; missing/corrupt reads as no state)
# ---------------------------------------------------------------------------
def load_pending() -> dict | None:
    """Read the pending confirmation state.

    Returns:
        dict | None: {"created_at", "basket_names", "items"} or None
        when the file is missing/corrupt/empty.
    """
    try:
        if OPTIMIZE_PENDING_PATH.exists():
            with open(OPTIMIZE_PENDING_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("items"):
                return data
    except (OSError, ValueError):
        pass
    return None


def save_pending(state: dict) -> None:
    """Persist the pending state atomically; empty items -> delete.

    Args:
        state: {"created_at", "basket_names", "items"}; when `items`
        is empty the pending file is removed instead of written.
    """
    if not state.get("items"):
        clear_pending()
        return
    OPTIMIZE_PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json", prefix="optimize_pending_",
        dir=str(OPTIMIZE_PENDING_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, OPTIMIZE_PENDING_PATH)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def clear_pending() -> None:
    """Remove the pending file (best-effort; missing file is fine)."""
    try:
        OPTIMIZE_PENDING_PATH.unlink()
    except OSError:
        pass


def _gen_code(used: set) -> str:
    """Draw a unique 3-letter code from the house alphabet."""
    while True:
        code = "".join(random.choice(CODE_ALPHABET)
                       for _ in range(CODE_LENGTH))
        if code not in used:
            used.add(code)
            return code


def assign_codes(gaps: list) -> list:
    """Attach a unique pending-code to every confirmable gap.

    Args:
        gaps: gap dicts (see classify_basket), action == "live".

    Returns:
        list: the same gap dicts, each with a "code" key added.
    """
    used: set = set()
    for gap in gaps:
        gap["code"] = _gen_code(used)
    return gaps


# ---------------------------------------------------------------------------
# Sheet index + row resolution (plan time — NO live search, NO writes)
# ---------------------------------------------------------------------------
def build_index(worksheet=None):
    """Build the plural-aware LookupIndex once per run.

    Args:
        worksheet: optional pre-connected worksheet.

    Returns:
        LookupIndex | None: None when the sheet is empty/unreadable.
    """
    from core.lookup import LookupIndex
    from core.sheets_client import connect_worksheet

    ws = worksheet
    if ws is None:
        ws = connect_worksheet()
    all_values = ws.get_all_values()
    if not all_values:
        return None
    return LookupIndex(all_values[1:], all_values[0])


def resolve_rows(names: list, idx=None, worksheet=None) -> dict:
    """Resolve basket keywords to sheet rows via lookup steps 1-3 ONLY.

    Mirrors LookupEngine.find_product's sheet steps (exact -> Col P
    alias -> partial auto-pick) but STOPS before step 5 — plan-time
    classification must never fire a live search. Row dicts also carry
    the raw keyword cells (ww_kw / coles_kw) so the caller can tell a
    missing KEYWORD from a missing PRICE.

    Args:
        names: basket keywords.
        idx: pre-built LookupIndex (build_index()).
        worksheet: optional pre-connected worksheet (used when idx is
            None).

    Returns:
        dict: keyword -> {"row_index", "generic_name", "prices",
        "ww_kw", "coles_kw"} for keywords that match a sheet row;
        absent keys = no row.
    """
    from core.lookup import LookupIndex
    from core.sheets_client import connect_worksheet

    if idx is None:
        ws = worksheet
        if ws is None:
            ws = connect_worksheet()
        all_values = ws.get_all_values()
        if not all_values:
            return {}
        idx = LookupIndex(all_values[1:], all_values[0])

    resolved: dict = {}
    for name in names:
        row = None
        hit = idx.find_exact(name)
        if hit is None:
            hit = idx.find_alias_exact(name)
        if hit is None:
            hit = idx.find_alias_token(name)
        if hit is not None:
            row = hit
        else:
            cands = idx.find_candidates(name)
            if cands:
                top = cands[0]
                row_dict = idx.get_row(top.row_index)
                if row_dict is not None:
                    row = {"row_index": top.row_index,
                           "generic_name": top.generic_name,
                           "prices": dict(row_dict.get("prices", {}))}
        if row is not None:
            resolved[name] = {
                "row_index": row.get("row_index"),
                "generic_name": row.get("generic_name", ""),
                "prices": dict(row.get("prices", {})),
                "ww_kw": str(row.get("ww_kw", "") or ""),
                "coles_kw": str(row.get("coles_kw", "") or ""),
            }
    return resolved


def hydrate_matched_names(items: list, rows: dict) -> list:
    """Fill BasketItems' matched_names with the sheet's Col A names.

    The sheet-mode comparator pass does not set matched_names, but the
    buy lists must show the FULL product name (user rule 2026-09-03).
    Items whose keyword resolves to a row are rebuilt with
    matched_names = {store: generic_name} for their priced stores.

    Args:
        items: BasketItems from the sheet-mode compare pass.
        rows: output of resolve_rows() for the same keywords.

    Returns:
        list: new BasketItem list (unresolvable keywords pass through
        unchanged).
    """
    from core.price_comparator import BasketItem

    hydrated = []
    for item in items:
        row = rows.get(item.name)
        gname = (row or {}).get("generic_name") or ""
        if not gname:
            hydrated.append(item)
            continue
        hydrated.append(BasketItem(
            name=item.name,
            prices=dict(item.prices),
            sources=dict(item.sources),
            specials=dict(item.specials),
            brand=item.brand,
            is_woolworths_home_brand=item.is_woolworths_home_brand,
            matched_names={s: gname for s in item.prices},
            matched_sizes={s: gname for s in item.prices},
            closest=dict(item.closest),
            uom_reason=item.uom_reason,
            store_unavailable=list(item.store_unavailable),
        ))
    return hydrated


# ---------------------------------------------------------------------------
# Classification (plan time — the user's decision tree)
# ---------------------------------------------------------------------------
def find_substitute(keyword: str, store: str, exclude_row_index,
                    idx) -> dict | None:
    """Find the closest sheet row with a usable price for one store.

    "Closest substitute on the sheet" (user rule 2026-09-03): sibling
    rows sharing significant tokens (plural-aware) with the keyword,
    excluding the item's own row. Read-only — the substitute's price is
    used for the comparison and never written anywhere.

    Args:
        keyword: the basket keyword.
        store: the store whose price is missing.
        exclude_row_index: the item's own sheet row (or None).
        idx: pre-built LookupIndex.

    Returns:
        dict | None: {"row_index", "generic_name", "price"} of the best
        substitute, or None.
    """
    if idx is None:
        return None
    cands = idx.find_candidates(keyword)
    for cand in cands:
        if cand.row_index == exclude_row_index:
            continue
        row = idx.get_row(cand.row_index)
        if not row:
            continue
        price = (row.get("prices") or {}).get(store)
        if price:
            return {"row_index": row["row_index"],
                    "generic_name": row.get("generic_name", ""),
                    "price": float(price)}
    return None


def _queued_somewhere(row_name: str, store: str,
                      queued: dict | None) -> bool:
    """Is this row already queued on the to-do list?

    Queued means the pricing situation is already being handled
    (Wednesday refresh once the product is on the website list) — no
    action needed. Queues carry no prices; presence is matched on the
    normalised row name. The searched queue is RETIRED (2026-09-03
    user rule) — only the to-do list counts; a legacy "searched" key
    in `queued` is still honoured so old callers keep working.

    Args:
        row_name: the resolved sheet row's Col A name.
        store: the store whose side is missing.
        queued: {"todo": [...entries]} or None.

    Returns:
        bool: True when a pending entry for this row exists on the
        to-do list (any store — the user manages reminders together).
    """
    from core.name_matcher import KeywordIndex

    if not row_name:
        return False
    norm = KeywordIndex._normalize(row_name)
    for entry in (queued or {}).get("todo", []):
        if KeywordIndex._normalize(
                entry.get("generic_name", "")) == norm:
            return True
        if KeywordIndex._normalize(
                entry.get("keyword", "")) == norm:
            return True
    return False


def classify_basket(items: list, rows: dict, idx=None,
                    queued: dict | None = None) -> tuple:
    """Split sheet-priced basket items per the user's decision tree.

    Substitute prices (found on the sheet) are injected into the
    returned items (source "sub") — read-only, never written.

    Args:
        items: BasketItems from the sheet-mode compare pass.
        rows: resolve_rows() output (row refs + keyword cells).
        idx: pre-built LookupIndex (for substitute search).
        queued: {"searched": [entries], "todo": [entries]} pending
            queue entries (raw dicts from the two queue files).

    Returns:
        tuple: (items, entries) — items with substitute prices
        injected; entries = one dict per item that is NOT fully
        sheet-priced: {"keyword", "group", "action", "row_name",
        "row_index", "missing", "add", "sub_names"} where action is
        "queued" (info only), "sub" (info only), or "live"
        (confirmable). Group letters: A = Coles side missing, B =
        Woolworths side missing, C = both missing.
    """
    entries: list = []
    kw_field = {"woolworths": "ww_kw", "coles": "coles_kw"}

    for item in items:
        missing = [s for s in ("woolworths", "coles")
                   if s not in item.prices]
        if not missing:
            continue  # fully sheet-priced — straight to basket

        row = rows.get(item.name) or {}
        row_name = row.get("generic_name", "")
        group = ("C" if len(missing) == 2
                 else ("A" if missing[0] == "coles" else "B"))

        # 2b / 3: pricing missing or error -> closest sheet sub first.
        sub_names: dict = {}
        still_missing = []
        for store in missing:
            sub = find_substitute(item.name, store,
                                  row.get("row_index"), idx)
            if sub:
                sub_names[store] = sub["generic_name"]
                item.prices[store] = sub["price"]
                item.sources[store] = "sub"
                item.matched_names[store] = sub["generic_name"]
            else:
                still_missing.append(store)
        if not still_missing:
            entries.append({"keyword": item.name, "group": group,
                            "action": "sub", "row_name": row_name,
                            "row_index": row.get("row_index"),
                            "missing": missing, "add": False,
                            "sub_names": sub_names})
            continue

        missing = still_missing
        group = ("C" if len(missing) == 2
                 else ("A" if missing[0] == "coles" else "B"))

        if not row:
            # 4: not on the sheet — live search; add is the user's
            # explicit choice (+add at confirm time).
            entries.append({"keyword": item.name, "group": "C",
                            "action": "live", "row_name": "",
                            "row_index": None, "missing": missing,
                            "add": False, "sub_names": {}})
            continue

        # 2a / 4: keyword missing + already queued -> no action.
        kw_missing_sides = [s for s in missing
                            if not row.get(kw_field[s])]
        if (len(kw_missing_sides) == len(missing)
                and _queued_somewhere(row_name, missing[0], queued)):
            entries.append({"keyword": item.name, "group": group,
                            "action": "queued", "row_name": row_name,
                            "row_index": row.get("row_index"),
                            "missing": missing, "add": False,
                            "sub_names": {}})
            continue

        # 2b: pricing missing/error (keyword present) -> live fill
        # (price-only write; item stays flagged until resolved). Sides
        # that still carry a keyword are marked for keyword re-sync +
        # to-do reminder at execute time (user rule 2026-09-03).
        entries.append({"keyword": item.name, "group": group,
                        "action": "live", "row_name": row_name,
                        "row_index": row.get("row_index"),
                        "missing": missing, "add": False,
                        "kw_present": [s for s in missing
                                       if row.get(kw_field[s])],
                        "sub_names": sub_names})
    return items, entries


# ---------------------------------------------------------------------------
# Confirmation execution (explicit --confirm only)
# ---------------------------------------------------------------------------
def search_side(store: str, keyword: str, page_size: int = 5) -> tuple:
    """Live-search ONE store and rank results (deterministic).

    Args:
        store: "woolworths" | "coles".
        keyword: the search term.
        page_size: max results.

    Returns:
        tuple: (ranked_items, coles_status) — coles_status is "" for
        the Woolworths side.
    """
    if store == "woolworths":
        from extractors.woolworths_extractor import (
            fetch_woolworths_search_noauth,
        )
        try:
            items = fetch_woolworths_search_noauth(
                keyword, page_size=page_size) or []
        except Exception:
            items = []
        from core.lookup import rank_live_results
        return rank_live_results(keyword, items), ""
    from extractors.coles_extractor import fetch_coles_search_status
    items: list = []
    status = "unavailable"
    try:
        items, status = fetch_coles_search_status(
            keyword, page_size=page_size)
    except Exception:
        items, status = [], "unavailable"
    from core.lookup import rank_live_results
    return rank_live_results(keyword, items or []), status


def _resolve_unit(live_size: str) -> str:
    """Non-interactive Rule B: live size or the canonical marker."""
    size = str(live_size or "").strip()
    return size if size else UNIT_UNAVAILABLE


def _write_missing_store(item: dict, store: str, listing,
                         worksheet=None) -> dict:
    """Write the live PRICE for one store of an EXISTING row — NO keyword.

    User rule 2026-09-03 (loophole fix): keywords are written ONLY by
    the map/resolve flow. The keyword is what lets the Wednesday sync
    match the row against the store's website list, so writing it here
    (while the product is not actually on the website list) would make
    the row vanish from the wool/coles missing lists while its price
    silently goes stale. Price-only keeps the row flagged on the
    appropriate missing list until the user resolves it via the normal
    map flow — which is the step that writes the keyword and closes
    the Wednesday refresh loop.

    Args:
        item: pending gap dict (needs row_name).
        store: the store being filled.
        listing: a ranked live result (raw_name/price/size).
        worksheet: optional pre-connected worksheet.

    Returns:
        dict: {"ok": bool, "detail": str}.
    """
    from core.sheets_sync import update_single_price

    row_name = item.get("row_name") or ""
    unit = _resolve_unit(getattr(listing, "size", "") or "")
    price_res = update_single_price(
        row_name, store, float(listing.price), size=unit,
        worksheet=worksheet)
    if not price_res.get("wrote"):
        return {"ok": False,
                "detail": f"{store}: price write failed "
                          f"({price_res.get('error', 'unknown')})"}
    return {"ok": True,
            "detail": (f"{store}: price ${float(listing.price):.2f} "
                       f"written to '{row_name}' (row "
                       f"{price_res.get('row_index')}) — keyword NOT "
                       f"set, item stays on the missing list until "
                       f"resolved")}


def _add_new_product(item: dict, pair: dict,
                     worksheet=None) -> dict:
    """Add a NOT-on-sheet product via exact `search --add-item` rules.

    Pair passed -> one row carrying BOTH store prices (the second
    add_product_row call hits the exact-name guard and fills the other
    store's cell) + a searched-items entry per store listing. Single
    side only -> one row + one entry. Row keyword columns stay EMPTY
    and the user query is saved as the Col P alias (interpretation
    0.4) so the next sheet lookup finds it.

    Args:
        item: pending gap dict (group C, no row_name).
        pair: select_live_pair() output.
        worksheet: optional pre-connected worksheet.

    Returns:
        dict: {"ok": bool, "detail": str, "queued": list[str]}.
    """
    from core.sheets_sync import add_product_row

    ww = pair.get("ww")
    coles = pair.get("coles")
    keyword = item["keyword"]
    queued: list = []
    details: list = []

    writes = []
    if ww is not None:
        writes.append(("woolworths", ww))
    if coles is not None:
        writes.append(("coles", coles))
    if not writes:
        return {"ok": False,
                "detail": "no live results for either store",
                "queued": []}

    # Col A name: the Woolworths listing when present, else Coles'.
    row_name = (ww or coles).raw_name
    for store, listing in writes:
        unit = _resolve_unit(getattr(listing, "size", "") or "")
        res = add_product_row(
            generic_name=row_name,
            store=store,
            price=float(listing.price),
            brand=getattr(listing, "brand", "") or "",
            size=unit,
            category=getattr(listing, "category", "") or "",
            store_keyword="",
            alias=keyword,
            is_special=bool(getattr(listing, "is_special", False)),
            special_desc=getattr(listing, "special_desc", "") or "",
            worksheet=worksheet,
        )
        if res.get("merged"):
            details.append(f"{store}: merged into existing row "
                           f"{res.get('row_index')} — price updated")
        elif res.get("wrote"):
            details.append(f"{store}: ${float(listing.price):.2f} → "
                           f"new row {res.get('row_index')}")
        else:
            return {"ok": False,
                    "detail": f"{store}: sheet write failed "
                              f"({res.get('error', 'unknown')})",
                    "queued": []}
        # To-do queue entry per store listing (the website-add
        # reminder) — only AFTER the sheet write succeeded. The
        # searched queue is RETIRED (2026-09-03 user rule); the to-do
        # list (add_to_list) is the ONE reminder queue and is itself
        # dup-guarded (store + normalised generic name).
        from core.add_to_list import add_entry as todo_add
        try:
            result = todo_add(
                store, listing.raw_name, listing.raw_name, size=unit)
            if result["added"]:
                queued.append(result["entry"].get("code", ""))
            else:
                details.append(f"{store}: already on the to-do list")
        except (OSError, ValueError) as exc:
            details.append(f"{store}: queue write failed ({exc})")

    return {"ok": True, "detail": "; ".join(details), "queued": queued}


def _clear_stale_keyword_and_todo(item: dict, store: str, listing,
                                  worksheet=None) -> dict:
    """Clear the WRONG keyword + queue the right one on the TO-DO list
    (user rule 2026-09-03, final).

    When the missing side of an EXISTING row still has a keyword cell
    (price = "N/A <date>" or errored), that keyword is clearly
    incorrect — it never matched the store website list. On a confirmed
    live price:
      1. the wrong keyword is DELETED from the sheet
         (set_store_keyword with an empty value);
      2. the live price is written by the caller (update_single_price);
      3. the CORRECT keyword (the found store product name) is queued
         on the TO-DO list, so the user can check the website shopping
         list — adding the right item there and confirming via
         `add-to-list done` writes the keyword back and brings the row
         back to weekly refreshes.

    Args:
        item: pending gap dict (needs row_name).
        store: the store being re-synced.
        listing: the ranked live result whose name is the correct
            keyword.
        worksheet: optional pre-connected worksheet.

    Returns:
        dict: {"ok": bool, "detail": str, "added": bool} — added is
        True when a NEW to-do entry was created.
    """
    from core.sheets_sync import set_store_keyword
    from core.add_to_list import add_entry as todo_add

    row_name = item.get("row_name") or ""
    unit = _resolve_unit(getattr(listing, "size", "") or "")
    kw_res = set_store_keyword(row_name, store, "", worksheet=worksheet)
    if not kw_res.get("found"):
        return {"ok": False,
                "detail": (f"{store}: stale keyword clear failed "
                           f"({kw_res.get('error', 'unknown')})"),
                "added": False}
    try:
        todo = todo_add(store, listing.raw_name, row_name, size=unit)
        added = bool(todo.get("added"))
    except (OSError, ValueError) as exc:
        return {"ok": True,
                "detail": (f"{store}: wrong keyword cleared; correct "
                           f"one is '{listing.raw_name}' (to-do write "
                           f"failed: {exc})"),
                "added": False}
    if not added:
        return {"ok": True,
                "detail": (f"{store}: wrong keyword cleared; correct "
                           f"one '{listing.raw_name}' is already on "
                           f"your to-do list"),
                "added": False}
    return {"ok": True,
            "detail": (f"{store}: wrong keyword cleared + correct one "
                       f"'{listing.raw_name}' added to your to-do "
                       f"list"),
            "added": True}


def execute_confirmation(item: dict, worksheet=None) -> dict:
    """Run the live search + writes for ONE confirmed gap.

    Args:
        item: pending gap dict (code/keyword/group/row_name/add).
        worksheet: optional pre-connected worksheet.

    Returns:
        dict: {"code", "keyword", "group", "ok", "detail",
        "queued": list[str], "live": dict} — live is populated for
        compare-only C items (prices for the plan, nothing written).
    """
    group = item["group"]
    keyword = item["keyword"]
    result = {"code": item.get("code", ""), "keyword": keyword,
              "group": group, "ok": False, "detail": "", "queued": [],
              "live": {}}

    if group in ("A", "B"):
        store = "coles" if group == "A" else "woolworths"
        ranked, coles_status = search_side(store, keyword)
        if store == "coles" and coles_status in (
                "unavailable", "breaker_open", "cap_exceeded"):
            result["detail"] = "Coles not checked (unavailable)"
            return result
        if not ranked:
            result["detail"] = f"no {store} results for '{keyword}'"
            return result
        outcome = _write_missing_store(item, store, ranked[0],
                                       worksheet=worksheet)
        result["ok"] = outcome["ok"]
        result["detail"] = outcome["detail"]
        if outcome["ok"] and store in item.get("kw_present", []):
            # Stale keyword (price was N/A): clear it + to-do reminder
            # with the correct product (user rule 2026-09-03).
            resync = _clear_stale_keyword_and_todo(item, store, ranked[0],
                                                   worksheet=worksheet)
            result["detail"] += f" — {resync['detail']}"
            result["todo"] = resync.get("added", False)
        return result

    # Group C: both stores, pair-gated.
    ww_ranked, _ = search_side("woolworths", keyword)
    coles_ranked, coles_status = search_side("coles", keyword)
    coles_down = coles_status in ("unavailable", "breaker_open",
                                  "cap_exceeded")
    from core.lookup import select_live_pair
    pair = select_live_pair(keyword, ww_ranked,
                            [] if coles_down else coles_ranked)
    if item.get("row_name"):
        # Legacy unpriced row: PRICE-ONLY update in place, never
        # queue — regardless of the add flag (the row exists; the
        # add option is for not-on-sheet items only). Sides that still
        # carry a keyword get it re-synced + a to-do reminder.
        details = []
        ok_any = False
        for store, listing in (("woolworths", pair.get("ww")),
                               ("coles", pair.get("coles"))):
            if listing is None:
                details.append(f"{store}: no usable live match")
                continue
            outcome = _write_missing_store(item, store, listing,
                                           worksheet=worksheet)
            details.append(outcome["detail"])
            ok_any = ok_any or outcome["ok"]
            if outcome["ok"] and store in item.get("kw_present", []):
                resync = _clear_stale_keyword_and_todo(item, store,
                                                       listing,
                                                       worksheet=worksheet)
                details.append(resync["detail"])
        result["ok"] = ok_any
        result["detail"] = "; ".join(details)
        return result

    if not item.get("add"):
        # Compare-only: prices for the basket, nothing written.
        live: dict = {}
        for store, listing in (("woolworths", pair.get("ww")),
                               ("coles", pair.get("coles"))):
            if listing is not None:
                live[store] = {"name": listing.raw_name,
                               "price": float(listing.price)}
        if not live:
            result["detail"] = (
                "coles not checked (unavailable)" if coles_down
                else "no live results for either store")
            return result
        names = " + ".join(v["name"] for v in live.values())
        prices = " / ".join(f"${v['price']:.2f}" for v in live.values())
        result["ok"] = True
        result["detail"] = (f"compared only (nothing written): "
                            f"{names} {prices}")
        result["live"] = live
        return result

    outcome = _add_new_product(item, pair, worksheet=worksheet)
    result["ok"] = outcome["ok"]
    result["detail"] = outcome["detail"]
    result["queued"] = outcome.get("queued", [])
    return result


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
def format_info_lines(entries: list) -> list:
    """Plain no-action info lines for queued / substitute items.

    Args:
        entries: classify_basket() entries.

    Returns:
        list[str]: lines to print under the plan (may be empty).
    """
    lines = []
    queued = [e for e in entries if e.get("action") == "queued"]
    subs = [e for e in entries if e.get("action") == "sub"]
    if queued:
        lines.append("✔ Already queued for Wednesday (no action):")
        lines.extend(f"   {e.get('row_name') or e.get('keyword', '')}"
                     for e in queued)
    if subs:
        lines.append("✔ Using closest sheet substitute (not written):")
        for e in subs:
            for store, name in e.get("sub_names", {}).items():
                lines.append(f"   {e.get('keyword', '')} → {name} "
                             f"({store})")
    return lines


def inject_live(items: list, live_by_kw: dict) -> list:
    """Inject compare-only live results into sheet items.

    After a confirm where the user chose compare-only for not-on-sheet
    items, the sheet is unchanged — the live prices are merged into the
    items here so the final plan shows them (source "live", full live
    names).

    Args:
        items: BasketItems from the rebuild's sheet pass.
        live_by_kw: keyword -> {store: {"name", "price"}}.

    Returns:
        list: BasketItems with live results injected.
    """
    from core.price_comparator import BasketItem

    if not live_by_kw:
        return items
    out = []
    for item in items:
        live = live_by_kw.get(item.name)
        if not live:
            out.append(item)
            continue
        prices = {s: d["price"] for s, d in live.items()}
        out.append(BasketItem(
            name=item.name,
            prices=prices,
            sources={s: "live" for s in prices},
            specials=dict(item.specials),
            brand=item.brand,
            is_woolworths_home_brand=item.is_woolworths_home_brand,
            matched_names={s: d["name"] for s, d in live.items()},
            matched_sizes={s: d["name"] for s, d in live.items()},
            closest=dict(item.closest),
            uom_reason=item.uom_reason,
            store_unavailable=list(item.store_unavailable),
        ))
    return out


def format_confirmation_block(state: dict) -> str:
    """Render the confirmation list for the pending state.

    Confirmable gaps appear under their A/B/C group with codes;
    already-queued and sheet-substitute items are shown as no-action
    info. Includes the reply instruction (codes, optional '+add' for
    not-on-sheet items).

    Args:
        state: pending dict ({"items", ...}).

    Returns:
        str: the block.
    """
    lines = [header("Live search items — pls confirm", "🧠"), ""]
    items = state.get("items", [])
    for group in ("A", "B", "C"):
        group_items = [i for i in items if i.get("group") == group
                       and i.get("action", "live") == "live"]
        if not group_items:
            continue
        lines.append(f"⚠️ {group} — {GROUP_LABELS[group]}:")
        for pos, item in enumerate(group_items, 1):
            name = item.get("row_name") or (
                f"(not on sheet) {item.get('keyword', '')}")
            lines.append(f"   {group}.{pos} [{item.get('code', '')}] "
                         f"{name}")
        lines.append("")

    queued = [i for i in items if i.get("action") == "queued"]
    if queued:
        lines.append("✔ Already queued for Wednesday (no action):")
        for item in queued:
            lines.append(f"   {item.get('row_name') or item.get('keyword', '')}")
        lines.append("")

    subs = [i for i in items if i.get("action") == "sub"]
    if subs:
        lines.append("✔ Using closest sheet substitute (not written):")
        for item in subs:
            for store, name in item.get("sub_names", {}).items():
                lines.append(f"   {item.get('keyword', '')} → {name} "
                             f"({store})")
        lines.append("")

    lines.append("💬 Reply with the codes to live-search — e.g. "
                 "'KAT, ABC' or 'all'.")
    lines.append("Not-on-sheet items: add '+add' to ALSO save as a new "
                 "row + searched list (e.g. 'CLW+add'). Without it the "
                 "price is used for the basket only — nothing written.")
    return "\n".join(lines)


def parse_confirm(arg: str, valid_codes: list) -> tuple:
    """Parse the --confirm argument.

    Accepted forms: 'all', 'none', 'all+add', or a comma/space list of
    codes, each optionally suffixed with '+add' (case-insensitive).

    Args:
        arg: the raw --confirm value.
        valid_codes: codes currently pending.

    Returns:
        tuple: (codes: set, add_codes: set, error: str) — error is ""
        on success; when invalid, codes/add_codes are empty and error
        explains the valid codes.
    """
    requested = (arg or "").strip()
    lower = requested.lower()
    if lower == "none":
        return set(), set(), ""
    if lower in ("all", "all+add"):
        codes = set(valid_codes)
        add_codes = codes if lower == "all+add" else set()
        return codes, add_codes, ""
    tokens = [t for t in requested.replace(",", " ").split() if t]
    if not tokens:
        return set(), set(), "no codes given"
    codes: set = set()
    add_codes: set = set()
    for token in tokens:
        m = re.fullmatch(r"([A-Za-z]{3})(?:\+?add)?", token)
        if not m:
            return set(), set(), f"unknown code: {token}"
        code = m.group(1).upper()
        if code not in valid_codes:
            return set(), set(), f"unknown code: {token}"
        codes.add(code)
        if token.lower().endswith("add"):
            add_codes.add(code)
    return codes, add_codes, ""
