"""v2 sheet-only read path (spec §6/§8). ONE master read + ONE
Local_Deals read per command. Never writes. Never live-searches."""
from __future__ import annotations

from core.halal import is_meat_term
from core.local_deals import (
    BUTCHERY_DOMAIN, PRODUCE_SUBCATEGORIES, SHOP_TAGS, STORE_COLUMNS,
    TAB_NAME, _numeric_price, tab_store_price,
)
from core.subcategory import normalize_subcategory

MASTER_TAB = "Products_Master"
ALIAS_DELIM = "|"
GONE_MARKER = "GONE"

_DOMAIN_LABELS = ({normalize_subcategory(s) for s in BUTCHERY_DOMAIN}
                  | {normalize_subcategory(s)
                     for s in PRODUCE_SUBCATEGORIES}
                  | {"butchery", "fruit & veg"})

_NA_RE_MARKERS = ("n/a", "unavailable")


def parse_master_row(sheet_row: int, row: list) -> dict | None:
    """One 13-col master grid row → lookup dict (None for blanks)."""
    name = str(row[0]).strip() if row else ""
    if not name:
        return None
    ww_raw = str(row[3]).strip() if len(row) > 3 else ""
    gone = ww_raw.upper() == GONE_MARKER
    na_marker = None
    low = ww_raw.lower()
    if not gone:
        for marker in _NA_RE_MARKERS:
            if low.startswith(marker):
                na_marker = ww_raw
                break
    return {
        "row": sheet_row,
        "name": name,
        "size": str(row[2]).strip() if len(row) > 2 else "",
        "ww_raw": ww_raw,
        "ww_num": _numeric_price(ww_raw),
        "keyword": str(row[6]).strip() if len(row) > 6 else "",
        "specials": str(row[7]).strip() if len(row) > 7 else "",
        "brand": str(row[4]).strip() if len(row) > 4 else "",
        "aliases": [a.strip() for a in
                    (str(row[9]).strip() if len(row) > 9 else "")
                    .split(ALIAS_DELIM) if a.strip()],
        "subcategory": normalize_subcategory(
            str(row[10]).strip() if len(row) > 10 else ""),
        "code": str(row[11]).strip() if len(row) > 11 else "",
        "gone": gone,
        "na_marker": na_marker,
    }


def parse_ld_row(sheet_row: int, row: list,
                 today=None) -> dict | None:
    """One 11-col Local_Deals row → {row, name, prices, code}.

    prices: {shop_key: (price, 'special' | 'permanent')} via
    core.local_deals.tab_store_price (special-first, expiry-aware).
    Structural rows (header / validity / section titles) → None.
    """
    name = str(row[0]).strip() if row else ""
    code = str(row[10]).strip() if len(row) > 10 else ""
    if not name and not code:
        return None
    if name in ("Prices valid until", "Product") or \
            name in ("FRUITS", "BUTCHERY", "OTHER"):
        return None
    prices: dict = {}
    for shop in SHOP_TAGS:
        price, kind = tab_store_price(row, shop, today=today)
        if price is not None:
            prices[shop] = (price, kind)
    return {"row": sheet_row, "name": name, "prices": prices,
            "code": code}


def read_tabs() -> tuple:
    """ONE master read + ONE Local_Deals read → (master, ld) dicts."""
    from core.sheets_client import connect_spreadsheet

    spreadsheet = connect_spreadsheet()
    master_grid = spreadsheet.worksheet(MASTER_TAB).get_all_values() \
        or []
    ld_grid = spreadsheet.worksheet(TAB_NAME).get_all_values() or []
    master = [parsed for i, row in enumerate(master_grid[1:], start=2)
              if (parsed := parse_master_row(i, row))]
    ld = [parsed for i, row in enumerate(ld_grid, start=1)
          if (parsed := parse_ld_row(i, row))]
    return master, ld


def is_meat_query(query: str) -> bool:
    """Meat-term gate (spec §5) — core.halal.is_meat_term."""
    return is_meat_term(query)


def _is_domain_row(master: dict) -> bool:
    """In-domain = halal-named (§5) OR a known meat/F&V sub-category.

    A BLANK sub-category is UNKNOWN, not out-of-domain — it answers
    the generic not-tracked class; out-of-domain needs positive
    evidence (a known non-meat/F&V label, e.g. 'crackers').
    """
    sub = master["subcategory"]
    return "halal" in master["name"].lower() or not sub \
        or sub in _DOMAIN_LABELS


def _best(prices: dict) -> tuple | None:
    """(shop, price, kind) of the cheapest local price, or None."""
    if not prices:
        return None
    shop = min(prices, key=lambda s: prices[s][0])
    price, kind = prices[shop]
    return shop, price, kind


def lookup_item(query: str, master_rows, ld_rows) -> dict:
    """Sheet-only lookup per the §8 table. NEVER raises on a miss.

    Match: exact Col A, then exact alias (col J), case-insensitive;
    a MEAT query resolves through halal-named rows only (spec §5).
    """
    q = str(query or "").strip()
    ql = q.lower()
    meat = is_meat_query(q)

    def _matches(name: str) -> bool:
        low = name.lower()
        if meat:
            return low == ql and "halal" in low
        return low == ql

    def _alias_matches(aliases) -> bool:
        if meat:
            return False           # meat resolves by halal NAME only
        return any(a.lower() == ql for a in aliases)

    hit = None
    for master in master_rows:
        if _matches(master["name"]) or \
                _alias_matches(master["aliases"]):
            hit = master
            break

    if hit is None and meat:
        # §8 row 3: meat term, no halal master row — fall back to
        # halal-named LOCAL rows (butcher prices + missing-list code).
        locals_with = [ld for ld in ld_rows
                       if "halal" in ld["name"].lower() and ld["prices"]]
        if locals_with:
            prices: dict = {}
            for ld in locals_with:
                for shop, (price, kind) in ld["prices"].items():
                    prices.setdefault(shop, (price, kind))
            best = _best(prices)
            return {"status": "meat-local-only", "master": None,
                    "local": prices, "best": best,
                    "code": locals_with[0]["code"],
                    "query": q}

    if hit is not None:
        ld = next((ld for ld in ld_rows
                   if ld["code"] and ld["code"] == hit["code"]), None)
        prices = dict(ld["prices"]) if ld else {}
        best = _best(prices)
        base = {"master": hit, "local": prices, "best": best,
                "code": hit["code"], "query": q}
        if hit["gone"]:
            base["status"] = "gone"
        elif hit["na_marker"]:
            base["status"] = "na"
        elif hit["ww_num"] is not None:
            base["status"] = "tracked"
        elif best is not None and _is_domain_row(hit):
            base["status"] = "missing"
        elif _is_domain_row(hit):
            base["status"] = "not-tracked"
        else:
            base["status"] = "out-of-domain"
        return base

    return {"status": "not-tracked", "master": None, "local": {},
            "best": None, "code": "", "query": q}


def missing_list(master_rows, ld_rows) -> list:
    """§6 rule: local side has ≥1 shop price AND D has no real price
    AND D != GONE AND keyword col G empty. Every entry carries its
    Item_Code. N/A + keyword = tracked-but-unavailable, NOT missing
    (§17.6) — the keyword-empty test covers it."""
    by_code = {ld["code"]: ld for ld in ld_rows if ld["code"]}
    items: list = []
    for master in master_rows:
        if master["gone"] or master["keyword"]:
            continue
        if master["ww_num"] is not None:
            continue
        ld = by_code.get(master["code"])
        if not ld or not ld["prices"]:
            continue
        best = _best(ld["prices"])
        items.append({"code": master["code"], "name": master["name"],
                      "best_local": (best[1], best[0]) if best else None,
                      "shops": sorted(ld["prices"])})
    return items


def _shop_label(shop_key: str) -> str:
    return dict(STORE_COLUMNS).get(shop_key, shop_key)


def _local_lines(result: dict) -> list:
    lines: list = []
    for shop, (price, kind) in sorted(
            result["local"].items(),
            key=lambda kv: kv[1][0]):
        tag = {"special": "special", "permanent": ""}[kind]
        suffix = f" ({tag})" if tag else ""
        lines.append(f"  {_shop_label(shop)}: ${price:.2f}{suffix}")
    return lines


def render_lookup(result: dict) -> str:
    """Style-LITE plain lines (style kit lands in Round 3)."""
    from core.woolworths_discounts import format_discounted_price, \
        is_woolworths_home_brand

    status = result["status"]
    master = result.get("master")
    lines: list = []

    if status == "tracked":
        name = master["name"]
        home = is_woolworths_home_brand(name, master["brand"])
        lines.append(f"{name} — Woolworths "
                     f"{format_discounted_price(master['ww_num'], home)}"
                     + (f" · {master['size']}" if master["size"] else ""))
    elif status == "gone":
        lines.append(f"{master['name']} — GONE at Woolworths")
    elif status == "na":
        lines.append(f"{master['name']} — unavailable this week "
                     f"({master['na_marker']})")
    elif status == "missing":
        lines.append(f"{master['name']} — not tracked at Woolworths, "
                     f"on the missing list [{master['code']}]")
    elif status == "meat-local-only":
        lines.append("Not tracked at Woolworths — missing list "
                     f"[{result['code']}]")
    elif status == "out-of-domain":
        return "Not tracked — outside local-shop domains"
    else:
        return "Not tracked" + (
            f" [{result['code']}]" if result.get("code") else "")

    lines.extend(_local_lines(result))
    best = result.get("best")
    if best:
        lines.append(f"  🏆 Best local: ${best[1]:.2f} — "
                     f"{_shop_label(best[0])}")
    code = result.get("code")
    if code and status in ("tracked", "gone", "na"):
        lines.append(f"  [{code}]")
    return "\n".join(lines)


def render_list(items: list) -> str:
    """'[CODE] name — best $X (shop)' lines + count."""
    if not items:
        return "The missing list is empty — every local price is at Woolworths."
    lines: list = []
    for item in items:
        best = item.get("best_local")
        best_txt = ""
        if best:
            price, shop = best
            best_txt = f" — best ${price:.2f} ({_shop_label(shop)})"
        lines.append(f"[{item['code']}] {item['name']}{best_txt}")
    lines.append("")
    lines.append(f"📋 {len(items)} item(s) on the missing list")
    return "\n".join(lines)
