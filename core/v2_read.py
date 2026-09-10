"""v2 sheet-only read path (spec §6/§8). ONE master read + ONE
Local_Deals read per command. Never writes. Never live-searches."""
from __future__ import annotations

import re

from pathlib import Path

from core.halal import is_meat_term
from core.local_deals import (
    BUTCHERY_DOMAIN, PRODUCE_SUBCATEGORIES, SHOP_TAGS, STORE_COLUMNS,
    TAB_NAME, _numeric_price, tab_store_price,
)
from core.subcategory import normalize_subcategory

MASTER_TAB = "Products_Master"
ALIAS_DELIM = "|"
GONE_MARKER = "GONE"
VALIDITY_LABEL = "Prices valid until"
IGNORED_PATH = (Path(__file__).resolve().parent.parent / "data"
                / "ignored_items.txt")

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
    if name in (VALIDITY_LABEL, "Product") or \
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


_TWIN_STRIP_TOKENS = ("halal", "non", "and")


def _non_halal_twin(query: str, master_rows: list) -> list:
    """Plain (non-halal) Woolworths master rows matching a MEAT query.

    Match rule (binding): strip the tokens 'halal'/'non'/'and' from
    the query; a plain DOMAIN row matches iff its normalized name
    contains EVERY remaining query token (word-boundary-safe — the
    subcategory.py discipline), its name does NOT contain 'halal',
    and it is not the halal row already answering. Returns [{'name',
    'state': 'priced'|'gone'|'na', 'value': float|str|None}] — the
    row set the RENDERER shows; no other consumer exists.

    Spec §18 A4: reads master_rows ONLY (never Local_Deals — locals
    are always the halal side) and never consults the answering halal
    row's col D. Blank-D plain rows carry no price state → omitted.
    """
    tokens = [t for t in re.findall(r"[a-z0-9]+", str(query or "").lower())
              if t not in _TWIN_STRIP_TOKENS]
    if not tokens:
        return []
    twins: list = []
    for master in master_rows:
        name = str(master["name"] or "").lower()
        if "halal" in name or not _is_domain_row(master):
            continue
        if not all(re.search(rf"\b{re.escape(tok)}\b", name)
                   for tok in tokens):
            continue
        if master["gone"]:
            twins.append({"name": master["name"], "state": "gone",
                          "value": None})
        elif master["na_marker"]:
            twins.append({"name": master["name"], "state": "na",
                          "value": master["na_marker"]})
        elif master["ww_num"] is not None:
            twins.append({"name": master["name"], "state": "priced",
                          "value": master["ww_num"]})
    return twins


def lookup_item(query: str, master_rows, ld_rows) -> dict:
    """Sheet-only lookup per the §8 table. NEVER raises on a miss.

    Match: exact Col A, then exact alias (col J), case-insensitive;
    a MEAT query resolves through halal-named rows only (spec §5).
    """
    q = str(query or "").strip()
    ql = q.lower()
    meat = is_meat_query(q)
    twins = _non_halal_twin(q, master_rows) if meat else []

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
                    "non_halal_twins": twins,
                    "query": q}

    if hit is not None:
        ld = next((ld for ld in ld_rows
                   if ld["code"] and ld["code"] == hit["code"]), None)
        prices = dict(ld["prices"]) if ld else {}
        best = _best(prices)
        base = {"master": hit, "local": prices, "best": best,
                "code": hit["code"], "non_halal_twins": twins,
                "query": q}
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
            "best": None, "code": "", "non_halal_twins": twins,
            "query": q}


def ignored_codes(path=None) -> set:
    """Codes hidden by the `ignore` verdict (spec §6).

    The ignore file's v2 lines start with '[CODE]'; legacy free-text
    lines carry no code and never match. Missing/corrupt file -> an
    empty set.
    """
    path = Path(path) if path else IGNORED_PATH
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    codes: set = set()
    for line in lines:
        text = line.strip()
        if text.startswith("[") and "]" in text:
            code = text[1:text.index("]")].strip().upper()
            if code:
                codes.add(code)
    return codes


def missing_list(master_rows, ld_rows, ignored_path=None) -> list:
    """§6 rule: local side has ≥1 shop price AND D has no real price
    AND D != GONE AND keyword col G empty. Every entry carries its
    Item_Code. N/A + keyword = tracked-but-unavailable, NOT missing
    (§17.6) — the keyword-empty test covers it. Codes on the ignore
    list are HIDDEN (spec §6 — revealed only by the `ignored` verb)."""
    hidden = ignored_codes(ignored_path)
    by_code = {ld["code"]: ld for ld in ld_rows if ld["code"]}
    items: list = []
    for master in master_rows:
        if master["gone"] or master["keyword"]:
            continue
        if master["ww_num"] is not None:
            continue
        if master["code"] and master["code"].upper() in hidden:
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


# §11 emoji section headers: local shops by domain (butchery 🔪 /
# fruit shop 🍎); Woolworths itself is 🟢 (kit SECTION_ICONS).
_SHOP_ICONS = {"dunya": "🔪", "dunya_fb": "🔪", "merjan": "🔪",
               "fruitopia": "🍎", "abusalim": "🍎"}


def _local_lines(result: dict) -> list:
    """Aligned per-shop price lines (kit: aligned price columns)."""
    from core.telegram_format import _cells

    entries = sorted(result["local"].items(),
                     key=lambda kv: kv[1][0])
    labels = [f"{_SHOP_ICONS.get(shop, '·')} {_shop_label(shop)}"
              for shop, _ in entries]
    width = max((_cells(label) for label in labels), default=0)
    lines: list = []
    for label, (shop, (price, kind)) in zip(labels, entries):
        pad = " " * max(0, width - _cells(label))
        tag = {"special": " (special)", "permanent": ""}[kind]
        lines.append(f"  {label}{pad}  ${price:.2f}{tag}")
    return lines


def _twin_lines(result: dict) -> list:
    """Non-halal twin display lines (spec §18 A4) — one per twin, the
    EXACT test.md format. A priced twin goes through the EXISTING WW
    display-discount engine (§5); the twin dict carries no brand, so
    home-brand detection runs on the row name alone (the engine's
    blank-brand rule)."""
    from core.woolworths_discounts import format_discounted_price, \
        is_woolworths_home_brand

    lines: list = []
    for twin in result.get("non_halal_twins") or []:
        name = twin["name"]
        if twin["state"] == "priced":
            home = is_woolworths_home_brand(name, "")
            price = format_discounted_price(twin["value"], home)
            lines.append(f"also at Woolworths (non-halal): {price}"
                         f" — {name}")
        elif twin["state"] == "gone":
            lines.append(f"also at Woolworths (non-halal): GONE"
                         f" — {name}")
        else:
            lines.append(f"also at Woolworths (non-halal): unavailable"
                         f" ({twin['value']}) — {name}")
    return lines


def render_lookup(result: dict) -> str:
    """Style-Kit v2 block (spec §11): emoji section headers, the item
    name on its own (bold-by-structure) line, aligned price columns,
    🏆 winner badge, GONE badge, compact footer (date + code legend).
    Answer LOGIC is the §8 table — unchanged from Round 2."""
    from core.telegram_format import GONE_BADGE, legend_footer, \
        section_header, winner_line
    from core.woolworths_discounts import format_discounted_price, \
        is_woolworths_home_brand

    status = result["status"]
    master = result.get("master")
    lines: list = []

    if status == "tracked":
        name = master["name"]
        home = is_woolworths_home_brand(name, master["brand"])
        # item line: the name leads its own block (structural bold)
        head = name + (f" · {master['size']}" if master["size"]
                       else "")
        if home:
            head += "  🏠"
        lines.append(head)
        ww_price = format_discounted_price(master["ww_num"], home)
        lines.append(f"  {section_header('Woolworths')}  {ww_price}")
    elif status == "gone":
        lines.append(f"{master['name']}")
        lines.append(f"  {GONE_BADGE} at Woolworths")
    elif status == "na":
        lines.append(f"{master['name']}")
        lines.append(f"  🟢 Woolworths — unavailable this week "
                     f"({master['na_marker']})")
    elif status == "missing":
        lines.append(f"{master['name']}")
        lines.append(f"  not tracked at Woolworths — missing list "
                     f"[{master['code']}]")
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
        lines.append(f"  {winner_line(best[1], _shop_label(best[0]))}")
    # §18 A4: the non-halal Woolworths twin side — after the local
    # lines + winner, before the code/footer.
    lines.extend(_twin_lines(result))
    code = result.get("code")
    if code and status in ("tracked", "gone", "na"):
        lines.append(f"  [{code}]")
    if status in ("tracked", "gone", "na", "missing",
                  "meat-local-only"):
        lines.append(f"  {legend_footer()}")
    return "\n".join(lines)


def render_list(items: list) -> str:
    """The ONE list, styled (spec §6/§11): 📋 header, '[CODE] name —
    best $X (shop)' lines, count + compact footer."""
    from core.telegram_format import legend_footer, section_header

    if not items:
        return "The missing list is empty — every local price is at Woolworths."
    lines: list = [section_header("Missing list")]
    for item in items:
        best = item.get("best_local")
        best_txt = ""
        if best:
            price, shop = best
            best_txt = f" — best ${price:.2f} ({_shop_label(shop)})"
        lines.append(f"[{item['code']}] {item['name']}{best_txt}")
    lines.append("")
    lines.append(f"📋 {len(items)} item(s) on the missing list")
    lines.append(legend_footer())
    return "\n".join(lines)
