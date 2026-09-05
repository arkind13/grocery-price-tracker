"""Local-deals pipeline: orchestration, tab rebuild, domain-gated
matching, detection, report rendering (§5-§9)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.basket_optimizer import DEFAULT_SPLIT_THRESHOLD  # noqa: F401
from core.name_matcher import similarity_tokens, token_set_ratio
from core.subcategory import normalize_subcategory

ALERT_PCT = 20.0                # strictly greater (20.0 -> no alert)
MATCH_MIN_RATIO = 0.65          # master-match threshold (§1.4.3)
MSG_CHAR_LIMIT = 4000           # hard pre-send check (4096 budget)
SYDNEY_TZ = "Australia/Sydney"
STATE_PATH = (Path(__file__).resolve().parent.parent / "data"
              / "local_deals_cron_state.json")

# Butchery comparison domain — the SAME label set as
# HALAL_CHECK_CATEGORIES (spec §8.4; unified in step S23).
from core.halal import HALAL_CHECK_CATEGORIES as BUTCHERY_DOMAIN
FRUITSHOP_COARSE = "fruit & veg"   # Col B authority (normalised)
PRODUCE_SUBCATEGORIES = {          # taxonomy produce labels
    "spring onion", "onion", "bananas", "blueberries", "raspberries",
    "strawberries", "apples", "capsicum", "cucumber", "tomato",
    "fresh herbs", "potatoes", "salad", "fruit & veg",
}

STOPWORDS = {"kg", "each", "ea", "pack", "bag", "box", "fresh"}
VARIETY_TOKENS = {
    "royal gala", "pink lady", "granny smith", "fuji", "jazz",
    "cos", "iceberg", "jap", "butternut", "sebago", "desiree",
    "truss", "cherry", "roma", "round",
}

TELEGRAM_CHAT_ID = -1004394070843   # Claw Command Center (mirror CLI)
TELEGRAM_USER_ID = 1594431983       # DM fallback (D24)
LOCAL_DEALS_TOPIC_ENV = "TELEGRAM_LOCAL_DEALS_TOPIC_ID"


def canonical_key(item_name: str) -> tuple:
    """Variety-aware canonical grouping key (RF1, sandbox test3 18/18).

    Word-order-insensitive tokens via name_matcher.similarity_tokens,
    stopwords + pure numbers stripped; a variety qualifier is REQUIRED
    in the key when present ("Beef Diced" == "Diced Beef"; "Royal
    Gala" never merges with "Pink Lady"). Returns (base, variety).

    Args:
        item_name: raw product/deal name.

    Returns:
        (base, variety) — both sorted token tuples; variety phrases
        contribute their component words to neither part twice.
    """
    name = (item_name or "").lower()
    tokens = {t for t in similarity_tokens(name)
              if t not in STOPWORDS and not re.fullmatch(r"\d+(\.\d+)?", t)}
    variety: set[str] = set()
    for v in VARIETY_TOKENS:
        if any(vt in tokens for vt in v.split()):
            variety.add(v)
    if variety:
        tokens -= {w for v in variety for w in v.split()}
    return (tuple(sorted(tokens)), tuple(sorted(variety)))


def is_in_domain(store_kind: str, deal_category: str,
                 master_subcategory: str,
                 master_coarse_category: str) -> bool:
    """The DOMAIN GATE (§8.4, plan §1.4.2). BOTH sides checked.

    A butchery deal needs vision category 'butchery' AND master Col Q
    in BUTCHERY_DOMAIN; a fruit-shop deal needs vision 'fruits' AND
    (master Col B coarse == 'fruit & veg' OR Col Q in
    PRODUCE_SUBCATEGORIES). Anything else is out of domain.

    Args:
        store_kind: 'butchery' | 'fruits' (fb_flyer_fetch STORES).
        deal_category: vision category of the deal line.
        master_subcategory: master Col Q (normalised here).
        master_coarse_category: master Col B (normalised).

    Returns:
        True when the deal may be compared against the master row.
    """
    sub = normalize_subcategory(master_subcategory or "")
    coarse = normalize_subcategory(master_coarse_category or "")
    if store_kind == "butchery":
        return deal_category == "butchery" and sub in BUTCHERY_DOMAIN
    if store_kind == "fruits":
        return (deal_category == "fruits"
                and (coarse == FRUITSHOP_COARSE
                     or sub in PRODUCE_SUBCATEGORIES))
    return False


def _load_gate_state() -> dict:
    """Read the gate state file; missing/corrupt counts as not-fired."""
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def friday_gate_open(now: datetime | None = None) -> bool:
    """True iff now is Friday 05:00-05:59 Sydney AND not yet fired.

    DST-proof via zoneinfo. A missing/corrupt state file counts as
    not-fired (silently re-fires — D-LD1).

    Args:
        now: injectable clock (tests); defaults to real now.

    Returns:
        True when the Friday send window is open for today.
    """
    now_syd = (now or datetime.now()).astimezone(
        ZoneInfo(SYDNEY_TZ))
    if now_syd.weekday() != 4 or now_syd.hour != 5:
        return False
    state = _load_gate_state()
    return state.get("last_fire_date") != now_syd.date().isoformat()


def friday_gate_mark_fired(now: datetime | None = None) -> None:
    """Write {"last_fire_date": YYYY-MM-DD} (Sydney) after ANY fired
    run (success OR failure) — one send per Friday.

    Args:
        now: injectable clock (tests); defaults to real now.
    """
    now_syd = (now or datetime.now()).astimezone(
        ZoneInfo(SYDNEY_TZ))
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_fire_date": now_syd.date().isoformat()},
                   indent=2),
        encoding="utf-8")


SECTION_ORDER = ("FRUITS", "BUTCHERY", "OTHER")

STORE_COLUMNS = [  # full 4-store column order (spec §4.1)
    ("dunya", "Dunya Butchery"),
    ("merjan", "Merjan Brothers Quality Meats"),
    ("fruitopia", "Fruitopia Mt Druitt"),
    ("abusalim", "Abu Salim Fruit Market"),
]
TAB_NAME = "Local_Deals"


def ensure_local_deals_tab(spreadsheet) -> "Worksheet":
    """Return the Local_Deals worksheet, creating it when missing.

    Raises RuntimeError (secret-free) when creation fails.
    """
    try:
        return spreadsheet.worksheet(TAB_NAME)
    except Exception:  # noqa: BLE001 — missing tab falls through to create
        pass
    try:
        return spreadsheet.add_worksheet(title=TAB_NAME, rows=200, cols=5)
    except Exception as exc:  # noqa: BLE001 — secret-free re-raise
        raise RuntimeError(
            f"Failed to ensure {TAB_NAME} tab: "
            f"{exc.__class__.__name__}") from exc


def _store_kind(store_key: str) -> str:
    """'butchery' | 'fruits' for a store key ('' when unknown)."""
    from extractors.fb_flyer_fetch import STORES
    return next((s["kind"] for s in STORES if s["key"] == store_key), "")


def _section_for(deal: dict) -> str:
    """FRUITS for category 'fruits', BUTCHERY for 'butchery', else
    OTHER (out-of-domain items are recorded — B7/B10)."""
    if deal.get("category") == "fruits":
        return "FRUITS"
    if deal.get("category") == "butchery":
        return "BUTCHERY"
    return "OTHER"


def _display_name(deal: dict) -> str:
    """Canonical Col A text: item + ' /kg' | ' /ea' suffix for unit
    deals; bulk rows carry the size in the name ('Potatoes 5kg')."""
    item = str(deal.get("item") or "").strip()
    kind = deal.get("price_kind")
    if kind == "bulk_pack":
        size = str(deal.get("bulk_size") or "").strip()
        return f"{item} {size}".strip()
    unit = deal.get("unit")
    if unit == "kg":
        return f"{item} /kg"
    if unit == "ea":
        return f"{item} /ea"
    return item


def _money(value: float) -> str:
    """Fixed two-decimal dollar text ('$2.99')."""
    return f"${value:.2f}"


def _bulk_note(deal: dict) -> str:
    """'[multi buy 5kg for $2.99]' exact wording (plan §1.4.6)."""
    return (f"[multi buy {deal.get('bulk_size')} "
            f"for {_money(float(deal.get('price') or 0))}]")


def _multibuy_note(deal: dict) -> str:
    """'[multi buy 2 for $15.00 — $7.50/ea]' (effective_unit_rate
    math, read-only reuse of core.multibuy semantics)."""
    from core.multibuy import effective_unit_rate
    qty = int(deal.get("multibuy_qty") or 0)
    total = float(deal.get("price") or 0)
    rate = effective_unit_rate(qty, total)
    return (f"[multi buy {qty} for {_money(total)} "
            f"— {_money(rate)}/ea]")


def _cell_for(deal: dict):
    """Numeric price for single deals, note text otherwise, None
    when the price is missing entirely (blank cell)."""
    kind = deal.get("price_kind")
    price = deal.get("price")
    if kind == "bulk_pack":
        return _bulk_note(deal)
    if kind == "multibuy":
        return _multibuy_note(deal)
    if isinstance(price, (int, float)) and price > 0:
        return float(price)
    return None


def build_rows(all_store_deals: dict) -> dict:
    """{section: [[colA, dunya, merjan, fruitopia, abusalim], ...]}.

    Canonical rows (RF1): equivalent IN-DOMAIN items share ONE row
    keyed by canonical_key; bulk/multi-buy cells hold NOTE text while
    a unit-price store keeps its numeric cell on the same row (the
    maths never mixes them). Out-of-domain items NEVER merge into
    domain rows (Oreo rule) — standalone rows under OTHER.

    Args:
        all_store_deals: {store_key: [deal dicts with category +
            price_kind fields from the vision schema]}.

    Returns:
        section -> grid rows (5 cells each, "" for absent stores).
    """
    rows_by_section: dict[str, list[list]] = {
        s: [] for s in SECTION_ORDER}
    row_index: dict[tuple, int] = {}
    for store_key, deals in all_store_deals.items():
        for deal in deals:
            in_domain = deal.get("category") == _store_kind(store_key)
            if not in_domain:
                section = "OTHER"
                key = ("od", store_key,
                       canonical_key(deal.get("item") or ""))
            else:
                # One row per canonical base: bulk/multi-buy cells
                # hold NOTE text while a unit-price store keeps its
                # numeric cell on the SAME row (the maths never
                # mixes them — plan §1.4.3/S10).
                section = _section_for(deal)
                key = canonical_key(deal.get("item") or "")
            cell = _cell_for(deal)
            display = _display_name(deal)
            slot = row_index.get((section, key))
            if slot is None:
                grid_row = [display, "", "", "", ""]
                rows_by_section[section].append(grid_row)
                row_index[(section, key)] = \
                    len(rows_by_section[section]) - 1
                slot = row_index[(section, key)]
            col = next((i + 1 for i, (k, _n) in enumerate(STORE_COLUMNS)
                        if k == store_key), None)
            if col is not None and cell is not None:
                rows_by_section[section][slot][col] = cell
    return {s: rows for s, rows in rows_by_section.items() if rows}


def rebuild_tab(worksheet, rows_by_section: dict,
                store_keys: list[str]) -> None:
    """Wipe + rewrite the tab (idempotent). Freeze row 1. ONE batch
    update A1:E{N} (gspread update(values=..., range_name=...)).

    Args:
        worksheet: gspread/Fake worksheet handle for Local_Deals.
        rows_by_section: build_rows() output.
        store_keys: stores in THIS run (other columns stay blank).
    """
    active = {k.strip() for k in (store_keys or [])
              if k and k.strip()} or {k for k, _n in STORE_COLUMNS}
    grid = [["Product"] + [name for _k, name in STORE_COLUMNS]]
    for section in SECTION_ORDER:
        section_rows = rows_by_section.get(section) or []
        if not section_rows:
            continue
        grid.append([section, "", "", "", ""])
        for row in section_rows:
            row = list(row)
            for i, (k, _n) in enumerate(STORE_COLUMNS, start=1):
                if k not in active:
                    row[i] = ""  # columns not in this run stay blank
            grid.append(row)
    worksheet.clear()
    worksheet.freeze(rows=1)
    worksheet.update(values=grid, range_name=f"A1:E{len(grid)}")


@dataclass
class MatchResult:
    """One compared or recorded deal (fields per spec §6.4)."""
    store_key: str
    store_name: str
    item_name: str
    in_domain: bool
    alert: bool = False
    pct: float | None = None
    baseline_store: str = ""          # "Woolworths" | "Coles" | ""
    baseline_price: float | None = None
    flyer_price: float | None = None
    variety_conflict: bool = False
    matched_master: str = ""
    site_price_note: str = ""          # normal site price (Dunya)
    multibuy_note: str = ""            # bulk/multibuy note text
    deal_kind: str = "single"
    note: str = ""                     # informational lines
    _basis: str = "ea"                 # comparison basis: "kg" | "ea"


def _numeric_price(cell) -> float | None:
    """float > 0 when the cell parses as a price, else None (D-LD3).

    Decodes multi-buy cells via core.multibuy decode_multibuy_cell
    first (the rate IS the cell's price). Marker cells (N/A <date>,
    unavailable <date>, GONE, blank) return None.
    """
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell) if cell > 0 else None
    text = str(cell or "").strip()
    if not text:
        return None
    from core.multibuy import decode_multibuy_cell, effective_unit_rate
    decoded = decode_multibuy_cell(text)
    if decoded is not None:
        qty, total = decoded
        return effective_unit_rate(qty, total)
    try:
        value = float(text.replace("$", "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _load_master_rows(worksheet) -> list[dict]:
    """READ-ONLY Products_Master scan.

    Returns {row_index, name, category, size, wool_price,
    coles_price, subcategory} (numeric-decoded D/E). Fixed indices
    per the documented layout: A name, B coarse category, C size,
    D Woolworths, E Coles, Q Sub_Category. Never writes.
    """
    all_values = worksheet.get_all_values()
    if not all_values:
        return []

    def _cell(row: list, idx: int) -> str:
        return str(row[idx]).strip() if len(row) > idx else ""

    rows: list[dict] = []
    for i, row in enumerate(all_values[1:], start=2):
        name = _cell(row, 0)
        if not name:
            continue
        rows.append({
            "row_index": i,
            "name": name,
            "category": _cell(row, 1),
            "size": _cell(row, 2),
            "wool_price": _numeric_price(_cell(row, 3)),
            "coles_price": _numeric_price(_cell(row, 4)),
            "subcategory": normalize_subcategory(_cell(row, 16)),
        })
    return rows


def _variety_conflict(flyer_item: str, master_name: str) -> bool:
    """EC2 guard (sandbox test3 logic, verbatim semantics).

    Both sides name the SAME variety -> no conflict; different
    varieties -> conflict; master names a variety the flyer lacks
    (generic vs varietied) -> conflict.
    """
    flyer_words = set(re.findall(r"[a-z0-9]+", flyer_item.lower()))
    master_words = set(re.findall(r"[a-z0-9]+", master_name.lower()))
    fv = {v for v in VARIETY_TOKENS
          if any(t in flyer_words for t in v.split())}
    mv = {v for v in VARIETY_TOKENS
          if any(t in master_words for t in v.split())}
    if fv and mv:
        return fv != mv            # both specific, different varieties
    return bool(mv and not fv)     # master varietied, flyer generic


def _unit_prices_agree(deal: dict, master_row: dict) -> bool:
    """Unit-family gate (plan §1.4.4): kg<->weight sizes, ea<->count;
    never weight<->volume<->count. Per-kg exception is scoped here.

    kg deals need a parseable WEIGHT master size (both sides $/kg);
    ea deals need a COUNT size (or no parseable size at all — the
    common 'unit unavailable' case cannot contradict); anything else
    reports a unit mismatch.
    """
    from core.uom import FAMILY_COUNT, FAMILY_WEIGHT, parse_size
    unit = (deal.get("unit") or "").lower()
    parsed = parse_size(master_row.get("size") or "")
    if unit == "kg":
        return parsed is not None and parsed.family == FAMILY_WEIGHT
    if unit == "ea":
        return parsed is None or parsed.family == FAMILY_COUNT
    return True


def _master_unit_price(master_row: dict) -> tuple[float, str, str] | None:
    """Master baseline on its comparison basis.

    Returns (unit_price, basis, store_name) — $/kg when the size
    parses as weight, else the raw unit price on the 'ea' basis, from
    the cheaper numeric D/E cell. None when no numeric baseline.
    """
    from core.uom import FAMILY_WEIGHT, parse_size
    baseline = None
    for store, key in (("Woolworths", "wool_price"),
                       ("Coles", "coles_price")):
        price = master_row.get(key)
        if price is not None and (baseline is None
                                  or price < baseline[0]):
            baseline = (price, store)
    if baseline is None:
        return None
    parsed = parse_size(master_row.get("size") or "")
    if parsed is not None and parsed.family == FAMILY_WEIGHT \
            and parsed.value > 0:
        return (baseline[0] / (parsed.value / 1000.0), "kg",
                baseline[1])
    return (baseline[0], "ea", baseline[1])


def _deal_unit_price(deal: dict) -> tuple[float, str] | None:
    """Deal price on its comparison basis: (price, 'kg'|'ea')."""
    price = deal.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    unit = (deal.get("unit") or "").lower()
    if unit == "kg":
        return (float(price), "kg")
    return (float(price), "ea")


def _site_price_for(deal: dict,
                    site_catalogues: dict) -> tuple[float, str] | None:
    """(site price, basis) for a Dunya deal from the site catalogue.

    Token-set best match >= MATCH_MIN_RATIO; basis mirrors the deal
    unit. None when no catalogue / no match.
    """
    items = (site_catalogues or {}).get(deal.get("store_key")) or []
    if not items:
        return None
    best_ratio, best = 0.0, None
    for item in items:
        ratio = token_set_ratio(deal.get("item") or "",
                                item.get("name") or "")
        if ratio > best_ratio:
            best_ratio, best = ratio, item
    if best is None or best_ratio < MATCH_MIN_RATIO:
        return None
    price = best.get("regular_price") or best.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    basis = "kg" if (deal.get("unit") or "").lower() == "kg" else "ea"
    return (float(price), basis)


def match_and_detect(rows, master_rows, site_catalogues) -> list[MatchResult]:
    """Domain-gated matching + >20% detection (§8).

    Out-of-domain items return in_domain=False, never matched, never
    alerted, never annotated. Bulk/multibuy NEVER enter the maths —
    they render as notes only. Extra-stop aggregation is derived by
    render_post1 from baseline/flyer fields (strictly greater $3.00,
    unit prices only).

    Args:
        rows: flat deal dicts enriched with store_key/store_name.
        master_rows: _load_master_rows() output.
        site_catalogues: {store_key: [normalised catalogue items]}.

    Returns:
        MatchResult list in input (board) order.
    """
    from extractors.fb_flyer_fetch import STORES
    store_names = {s["key"]: s["name"] for s in STORES}
    results: list[MatchResult] = []
    for deal in rows:
        store_key = deal.get("store_key") or ""
        kind = str(deal.get("price_kind") or "single")
        result = MatchResult(
            store_key=store_key,
            store_name=deal.get("store_name")
            or store_names.get(store_key, store_key),
            item_name=str(deal.get("item") or ""),
            in_domain=False,
            deal_kind=kind,
        )
        if kind == "bulk_pack":
            size = deal.get("bulk_size") or ""
            from core.uom import FAMILY_WEIGHT, parse_size
            parsed = parse_size(size)
            per_unit = ""
            if parsed is not None and parsed.family == FAMILY_WEIGHT \
                    and parsed.value > 0 and deal.get("price"):
                per_kg = float(deal["price"]) / (parsed.value / 1000.0)
                per_unit = f" — {_money(per_kg)}/kg"
            result.multibuy_note = (
                f"multi buy {size} for "
                f"{_money(float(deal.get('price') or 0))}{per_unit}")
            if isinstance(deal.get("price"), (int, float)) \
                    and not isinstance(deal.get("price"), bool):
                result.flyer_price = float(deal["price"])
            result.item_name = f"{result.item_name} {size}".strip()
            results.append(result)
            continue
        if kind == "multibuy":
            from core.multibuy import effective_unit_rate
            qty = int(deal.get("multibuy_qty") or 0)
            total = float(deal.get("price") or 0)
            if qty >= 2 and total > 0:
                rate = effective_unit_rate(qty, total)
                result.multibuy_note = (
                    f"multi buy {qty} for {_money(total)} "
                    f"— {_money(rate)}/ea")
            if isinstance(deal.get("price"), (int, float)) \
                    and not isinstance(deal.get("price"), bool):
                result.flyer_price = float(deal["price"])
            results.append(result)
            continue

        store_kind = _store_kind(store_key)
        deal_side = (store_kind in ("butchery", "fruits")
                     and deal.get("category") == store_kind)
        # All single deals carry their printed price (out-of-domain
        # lines render it plainly in Post 2, 04:56 full-board rule).
        if isinstance(deal.get("price"), (int, float)) \
                and not isinstance(deal.get("price"), bool):
            result.flyer_price = float(deal["price"])
        if not deal_side:
            results.append(result)   # out-of-domain: plain, unannotated
            continue
        result.in_domain = True

        best_ratio, best_master = 0.0, None
        deal_tokens = similarity_tokens(deal.get("item") or "")
        for master in master_rows:
            if not is_in_domain(store_kind,
                                deal.get("category") or "",
                                master["subcategory"],
                                master["category"]):
                continue
            ratio = token_set_ratio(deal.get("item") or "",
                                    master["name"])
            containment = bool(deal_tokens) and deal_tokens.issubset(
                similarity_tokens(master["name"]))
            if (ratio >= MATCH_MIN_RATIO or containment) \
                    and ratio > best_ratio:
                best_ratio, best_master = ratio, master

        site = _site_price_for(deal, site_catalogues)
        if site is not None and result.flyer_price:
            site_price, site_basis = site
            denom = max(result.flyer_price, site_price)
            save_pct = round(
                (site_price - result.flyer_price) / denom * 100.0)
            result.site_price_note = (
                f"normal site price {_money(site_price)}/{site_basis}"
                f" — save {save_pct}%")
        elif store_kind == "butchery" and \
                str(deal.get("store_key")) == "dunya":
            result.site_price_note = "normal price unavailable"

        if best_master is None:
            # Distinguish no-match vs unit-family mismatch reporting
            result.note = "no sheet match"
            results.append(result)
            continue
        result.matched_master = best_master["name"]
        if _variety_conflict(deal.get("item") or "",
                             best_master["name"]):
            result.variety_conflict = True
            result.note = "variety differs — verify"
        if not _unit_prices_agree(deal, best_master):
            result.note = result.note or "unit mismatch"
            results.append(result)
            continue

        master_unit = _master_unit_price(best_master)
        deal_unit = _deal_unit_price(deal)
        if master_unit is None or deal_unit is None:
            results.append(result)
            continue
        baseline_unit_price, master_basis, baseline_store = master_unit
        flyer_unit_price, flyer_basis = deal_unit
        # Baseline display value: the chosen store's raw cell.
        result.baseline_store = baseline_store
        result.baseline_price = (
            best_master.get("wool_price")
            if baseline_store == "Woolworths"
            else best_master.get("coles_price"))
        # Bases must agree: a $/kg flyer needs a $/kg master baseline
        # (the kg->ea pairing was already blocked by
        # _unit_prices_agree above; this is defensive only).
        if flyer_basis == "kg" and \
                not _master_unit_price_is_kg(best_master):
            results.append(result)
            continue
        pct = ((baseline_unit_price - flyer_unit_price)
               / baseline_unit_price * 100.0)
        result.pct = pct
        result._basis = flyer_basis
        if pct > ALERT_PCT and not result.variety_conflict:
            result.alert = True
        results.append(result)
    return results


def _master_unit_price_is_kg(master_row: dict) -> bool:
    """True when the master baseline is on the $/kg basis."""
    from core.uom import FAMILY_WEIGHT, parse_size
    parsed = parse_size(master_row.get("size") or "")
    return parsed is not None and parsed.family == FAMILY_WEIGHT


def _unit_label(result: MatchResult) -> str:
    """'/kg' | '/ea' comparison label for a matched result."""
    return "/kg" if getattr(result, "_basis", "ea") == "kg" else "/ea"


def render_post1(results: list[MatchResult], friday_date: str) -> str:
    """Standouts only (§9). Exact formats of the sample block; the
    'Extra stop worth it: $X.XX total saving on N items' line appears
    once per qualifying store (savings strictly > $3.00, unit prices
    only). Empty -> 'No local standouts this week'.

    Args:
        results: match_and_detect() output.
        friday_date: YYYY-MM-DD label for the header.

    Returns:
        The Post 1 message text (never empty).
    """
    standouts = [r for r in results if r.alert]
    suppressed = [r for r in results if r.in_domain and r.variety_conflict
                  and r.pct is not None and r.pct > ALERT_PCT
                  and not r.alert]
    if not standouts and not suppressed:
        return "No local standouts this week"

    lines: list[str] = [
        f"🚨 LOCAL STANDOUTS — Fri {friday_date} (Mt Druitt)"]
    show = standouts + suppressed
    seen_stores: list[str] = []
    for r in show:
        if r.store_name.upper() not in seen_stores:
            seen_stores.append(r.store_name.upper())
    for store in seen_stores:
        lines.append("")
        lines.append(store)
        for r in show:
            if r.store_name.upper() != store:
                continue
            if not r.alert:
                # variety-suppressed standout: tag replaces the alert
                lines.append(
                    f" • {r.item_name} — {_money(r.flyer_price or 0)}"
                    f"{_unit_label(r)}  (variety differs — verify)")
                continue
            base = _money(r.baseline_price or 0)
            lines.append(
                f" • {r.item_name} — {_money(r.flyer_price or 0)}"
                f"{_unit_label(r)}  ({r.pct:.0f}% < "
                f"{r.baseline_store} {base}{_unit_label(r)})")
    # Extra-stop aggregation per store: strictly > $3.00, alerts only.
    for store in seen_stores:
        store_results = [r for r in standouts
                         if r.store_name.upper() == store]
        savings = sum(
            (r.baseline_price or 0) - (r.flyer_price or 0)
            for r in store_results)
        if savings > DEFAULT_SPLIT_THRESHOLD and store_results:
            lines.append("")
            lines.append(
                f"Extra stop worth it: {_money(savings)} total "
                f"saving on {len(store_results)} items")
    return "\n".join(lines)


def _split_oversized(block: str, store_header: str) -> list[str]:
    """Line-boundary split at MSG_CHAR_LIMIT with '(continued)' and
    the store header repeated on every chunk (§9 hard rule 2).

    Args:
        block: the full store block text.
        store_header: header line repeated on every chunk.

    Returns:
        List of message-sized chunks (>= 1).
    """
    if len(block) <= MSG_CHAR_LIMIT:
        return [block]
    body_lines = block.splitlines()
    body = [ln for ln in body_lines
            if ln.strip() and ln.strip() != store_header.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = len(store_header) + 2
    for line in body:
        if size + len(line) + 1 > MSG_CHAR_LIMIT - 16:
            chunks.append(store_header + "\n" + "\n".join(current)
                          + "\n(continued)")
            current, size = [], len(store_header) + 2
        current.append(line)
        size += len(line) + 1
    tail = store_header + "\n" + "\n".join(current)
    if current and chunks and len(chunks[-1]) + len(tail) > 0:
        chunks.append(tail)
    elif current:
        chunks.append(tail)
    return chunks or [block]


def render_post2_blocks(results, friday_date) -> list[str]:
    """Intro block (title + ⚠️ no-prices lines) then ONE block per
    store, natural board order, no sorting, EVERYTHING (04:56):
    out-of-domain items as plain unannotated lines. Shopping-list
    rule note appended when any multi-buy exists (B12).

    Args:
        results: match_and_detect() output (board order preserved).
        friday_date: YYYY-MM-DD label for the intro title.

    Returns:
        List of message texts: [intro, store block, ...] (each store
        block pre-split when oversized).
    """
    from extractors.fb_flyer_fetch import STORES
    active_stores = []
    for s in STORES:
        if any(r.store_key == s["key"] for r in results):
            active_stores.append(s)
    missing = [s for s in STORES if s not in active_stores]

    intro = [f"🛒 LOCAL BOARDS — Fri {friday_date} (Mt Druitt)"]
    intro += [f"⚠️ No prices found this week: {s['name']} "
              f"(no new board)" for s in missing]
    if any(r.multibuy_note for r in results):
        intro.append("Shopping-list note: multi-buy items need the "
                     "minimum purchase quantity at checkout.")

    blocks = ["\n".join(intro)]
    for s in STORES:
        store_results = [r for r in results if r.store_key == s["key"]]
        if not store_results:
            continue
        header = s["name"].upper()
        lines = [header]
        any_multibuy = False
        for n, r in enumerate(store_results, 1):
            price = (_money(r.flyer_price)
                     if r.flyer_price is not None else "?")
            if r.deal_kind == "bulk_pack":
                any_multibuy = True
                bracket = r.multibuy_note
                if r.site_price_note:
                    bracket += f" — {r.site_price_note}"
                lines.append(f" {n}. {r.item_name} — {price}")
                lines.append(f"    [{bracket}]")
            elif r.multibuy_note:
                any_multibuy = True
                lines.append(f" {n}. {r.item_name} — {price}"
                             f"  ({r.multibuy_note})")
            else:
                line = f" {n}. {r.item_name} — {price}"
                if r.pct is not None and r.pct > ALERT_PCT \
                        and r.baseline_store:
                    line += (f"  (also {r.pct:.0f}% < "
                             f"{r.baseline_store})")
                if r.site_price_note:
                    line += f"  ({r.site_price_note})"
                lines.append(line)
        block = "\n".join(lines)
        if any_multibuy:
            block += ("\nMulti-buy lines show the bundle total; "
                      "the per-unit rate is in brackets.")
        blocks.extend(_split_oversized(block, header))
    return blocks


def _env_int(name: str) -> int | None:
    """int value of an env var, or None when unset/non-numeric."""
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_upsert(key: str, value: str, env_path: Path) -> None:
    """Atomically replace-or-append ONE KEY=VALUE line in .env.

    Non-secret values only. File contents are NEVER printed.
    """
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    tmp = env_path.with_suffix(".env.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, env_path)


def _send_message(bot_token: str, chat_id, text: str,
                  thread_id=None) -> dict:
    """One Telegram sendMessage. Returns the PARSED API response
    ({"ok": bool, "message_id": int|None, "chat_id", "thread_id"})
    — unlike the CLI's bool sender, the receipt gate needs the
    message_id. Never raises; failures print a secret-free line.
    """
    import urllib.error
    import urllib.request

    result = {"ok": False, "message_id": None,
              "chat_id": chat_id, "thread_id": thread_id}
    if not bot_token:
        print("[telegram] no bot token configured — not sent")
        return result
    body: dict = {"chat_id": chat_id, "text": text}
    if thread_id is not None:
        body["message_thread_id"] = thread_id
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        result["ok"] = bool(data.get("ok"))
        msg = data.get("result") or {}
        result["message_id"] = msg.get("message_id")
        chat = msg.get("chat") or {}
        result["chat_id"] = chat.get("id", chat_id)
        return result
    except Exception as exc:  # noqa: BLE001 — delivery is best-effort
        print(f"[telegram] send failed: {exc.__class__.__name__}")
        return result


def deliver_reports(bot_token: str, post1: str,
                    post2_blocks: list[str], topic_id) -> None:
    """Length-check EVERY message <= 4000 BEFORE send (never rely on
    truncation); topic post when topic_id is set, otherwise DM +
    console note. Best-effort; never raises. Prints one secret-free
    receipt line per message:
    '[telegram] ok message_id=<id> chat=<id> thread=<id|dm>' — the
    S32 receipt gate greps these. Writes the first-fire receipt file
    when at least one message was accepted. When EVERY topic send
    fails, a secret-free failure summary still lands in the DM (the
    build never goes silent).
    """
    messages = [post1] + [b for b in (post2_blocks or []) if b]
    route = "topic" if topic_id else "dm"
    receipts: list[dict] = []
    for text in messages:
        if len(text) > MSG_CHAR_LIMIT:
            print(f"[telegram] message exceeds {MSG_CHAR_LIMIT} "
                  f"chars — NOT sent (never truncate)")
            continue
        if route == "topic":
            receipt = _send_message(bot_token, TELEGRAM_CHAT_ID, text,
                                    thread_id=topic_id)
        else:
            receipt = _send_message(bot_token, TELEGRAM_USER_ID, text)
        receipt["chars"] = len(text)
        receipts.append(receipt)
        if receipt["ok"]:
            thread = receipt["thread_id"] if route == "topic" else "dm"
            print(f"[telegram] ok message_id={receipt['message_id']} "
                  f"chat={receipt['chat_id']} thread={thread}")
    if route == "topic" and receipts and \
            not any(r["ok"] for r in receipts):
        print("[telegram] all topic sends failed — paging via DM")
        _send_message(
            bot_token, TELEGRAM_USER_ID,
            f"[local-deals] delivery failed: 0/{len(receipts)} "
            f"messages reached the topic — check the run log.")
    _write_first_fire_receipt(receipts, route)


FIRST_FIRE_PATH = (Path(__file__).resolve().parent.parent / "data"
                   / "local_deals_first_fire.json")


def _write_first_fire_receipt(receipts: list[dict], route: str) -> None:
    """Audit file for the S32 gate: {"fired_at": ISO, "route",
    "messages": [{"message_id", "thread_id", "chars"}]} — written
    only when at least one message got ok=True."""
    oks = [r for r in receipts or [] if r.get("ok")]
    if not oks:
        return
    payload = {
        "fired_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "route": route,
        "messages": [{"message_id": r.get("message_id"),
                      "thread_id": r.get("thread_id"),
                      "chars": r.get("chars", 0)} for r in oks],
    }
    FIRST_FIRE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIRST_FIRE_PATH.write_text(json.dumps(payload, indent=2),
                               encoding="utf-8")


def provision_local_deals_topic(bot_token: str = "") -> dict:
    """AUTONOMOUS topic provisioning (§9 S31; user revision
    2026-09-05 07:38 — supersedes manual M1).

    Chain (fully automatic, no user action, no deferral):
    1. TELEGRAM_LOCAL_DEALS_TOPIC_ID already set -> verify with one
       test send to that thread; done.
    2. Bot API createForumTopic(chat_id=TELEGRAM_CHAT_ID,
       name='local-deals') -> message_thread_id.
    3. Atomic .env upsert of TELEGRAM_LOCAL_DEALS_TOPIC_ID=<id>
       (non-secret id; contents NEVER printed).
    4. Test send to the new thread; receipt logged.
    5. Rights-blocked creation (HTTP 400 'not enough rights') is NOT
       a stop: route falls back to DM (TELEGRAM_USER_ID), and topic
       creation retries on every later provisioning call.

    Returns {"route": "topic"|"dm", "thread_id": int|None,
    "created": bool, "receipt": <api response>}.
    """
    import urllib.error
    import urllib.request

    bot_token = bot_token or os.getenv("TELEGRAM_CLAW_BOT", "")
    result: dict = {"route": "dm", "thread_id": None,
                    "created": False, "receipt": {}}
    existing = _env_int(LOCAL_DEALS_TOPIC_ENV)
    if existing:
        test = _send_message(bot_token, TELEGRAM_CHAT_ID,
                             "[local-deals] topic check",
                             thread_id=existing)
        result.update(route="topic", thread_id=existing,
                      receipt=test)
        print(f"[local-deals] telegram route: topic "
              f"(thread_id={existing}, created=False)")
        return result
    if not bot_token:
        print("[local-deals] no TELEGRAM_CLAW_BOT token — DM route; "
              "topic creation will retry on the next run")
        return result
    try:
        body = json.dumps({"chat_id": TELEGRAM_CHAT_ID,
                           "name": "local-deals"}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}"
            f"/createForumTopic",
            data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001 — body read is best-effort
            pass
        print(f"[local-deals] topic creation blocked "
              f"(HTTP {exc.code}) — DM fallback; retries next run")
        if detail:
            print(f"[local-deals] api note: "
                  f"{detail.split('description')[-1][:120]}")
        return result
    except Exception as exc:  # noqa: BLE001 — network/transport
        print(f"[local-deals] topic creation failed "
              f"({exc.__class__.__name__}) — DM fallback; retries "
              f"next run")
        return result
    if not data.get("ok"):
        print("[local-deals] topic creation refused by api — "
              "DM fallback; retries next run")
        return result
    thread_id = (data.get("result") or {}).get("message_thread_id")
    if not thread_id:
        print("[local-deals] api returned no thread id — DM fallback")
        return result
    from core.sheets_client import _find_root_env
    _env_upsert(LOCAL_DEALS_TOPIC_ENV, str(thread_id),
                _find_root_env())
    test = _send_message(bot_token, TELEGRAM_CHAT_ID,
                         "[local-deals] local butchery + fruit shop "
                         "deals will post in this topic.",
                         thread_id=thread_id)
    result.update(route="topic", thread_id=thread_id, created=True,
                  receipt=test)
    print(f"[local-deals] telegram route: topic "
          f"(thread_id={thread_id}, created=True)")
    return result


def _process_store(store: dict, run_dir: Path, today_syd) -> list[dict]:
    """One store: fetch -> per-post vision -> freshness filter.

    Raises (FetchUnavailable / VisionUnavailable) on total failure —
    the caller records the store as failed (⚠️ line, exit code).
    Zero parsed deals also raises (no new board = failure by design).

    Args:
        store: STORES entry.
        run_dir: per-run flyer directory (wiped per store inside).
        today_syd: Sydney date for the valid_until freshness drop.

    Returns:
        Deal dicts enriched with store_key/store_name/post_ref.
    """
    from extractors.fb_flyer_fetch import fetch_store_posts
    from core.flyer_vision import parse_board_images

    posts = fetch_store_posts(store, run_dir)
    deals: list[dict] = []
    for post in posts:
        payload = parse_board_images(post.files)
        valid_until = payload.get("valid_until")
        if valid_until:
            try:
                if date.fromisoformat(str(valid_until)) < today_syd:
                    continue   # expired board — freshness drop (§5)
            except ValueError:
                pass           # unparseable date keeps the post
        for deal in payload.get("deals") or []:
            deals.append({**deal,
                          "store_key": store["key"],
                          "store_name": store["name"],
                          "post_ref": post.post_ref})
    if not deals:
        from extractors.fb_flyer_fetch import FetchUnavailable
        raise FetchUnavailable("no deals parsed from any post")
    return deals


def run_local_deals(stores=None, dry_run: bool = False,
                    send_telegram: bool = True,
                    refresh_catalogue: bool = False) -> int:
    """The §5 pipeline. ThreadPoolExecutor(max_workers=4), one future
    per store; posts sequential within a store. Freshness drop after
    vision (valid_until < today Sydney; all-null dates keep posts).
    Sheet rebuild unless dry_run. Telegram unless dry_run or
    send_telegram False (then stdout). Returns 0 success, 1 partial
    failure with report still sent, 2 total failure.

    Args:
        stores: store keys to run (default all four).
        dry_run: fetch+parse+match+report to stdout only.
        send_telegram: deliver the two posts via Telegram.
        refresh_catalogue: force the Dunya site-catalogue walk.
    """
    from concurrent.futures import ThreadPoolExecutor

    from core.sheets_client import _load_env
    _load_env()
    from extractors.fb_flyer_fetch import FLYERS_DIR, STORES
    from extractors.fb_flyer_fetch import FetchUnavailable
    from core.flyer_vision import VisionUnavailable  # noqa: F401

    wanted = {s.strip() for s in (stores or []) if s and s.strip()}
    active = [s for s in STORES if not wanted or s["key"] in wanted]
    if not active:
        print(f"[local-deals] unknown stores: {sorted(wanted)}")
        return 2
    today_syd = datetime.now().astimezone(
        ZoneInfo(SYDNEY_TZ)).date()
    friday_label = today_syd.isoformat()
    run_dir = FLYERS_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")

    # Dunya site catalogue loads ONCE before the fan-out (D14).
    site_catalogues: dict[str, list[dict]] = {}
    try:
        from extractors.shop_site_catalogue import (
            get_normalised_catalogue,
        )
        catalogue = get_normalised_catalogue(
            "dunya", force=refresh_catalogue)
        if catalogue:
            site_catalogues["dunya"] = catalogue
    except Exception as exc:  # noqa: BLE001 — degrade to no site note
        print(f"[local-deals] site catalogue unavailable: "
              f"{exc.__class__.__name__}")

    store_deals: dict[str, list[dict]] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {s["key"]: pool.submit(_process_store, s, run_dir,
                                         today_syd)
                   for s in active}
        for key, future in futures.items():
            try:
                store_deals[key] = future.result()
            except Exception as exc:  # noqa: BLE001 — store isolation
                failures.append(key)
                kind = exc.__class__.__name__
                if isinstance(exc, (FetchUnavailable,)):
                    print(f"[local-deals] {key}: {exc}")
                else:
                    print(f"[local-deals] {key}: {kind}")

    flat_rows = [d for deals in store_deals.values() for d in deals]
    master_rows: list[dict] = []
    try:
        from core.sheets_client import connect_worksheet
        master_rows = _load_master_rows(connect_worksheet())
    except Exception as exc:  # noqa: BLE001 — matching degrades
        print(f"[local-deals] master read failed "
              f"({exc.__class__.__name__}) — matching degraded")

    results = match_and_detect(flat_rows, master_rows,
                               site_catalogues)

    if not dry_run and store_deals:
        try:
            from core.sheets_client import connect_spreadsheet
            spreadsheet = connect_spreadsheet()
            worksheet = ensure_local_deals_tab(spreadsheet)
            rows_by_section = build_rows(store_deals)
            rebuild_tab(worksheet, rows_by_section,
                        list(store_deals.keys()))
        except Exception as exc:  # noqa: BLE001 — tab write is not
            # allowed to kill the report; the run still delivers.
            print(f"[local-deals] tab rebuild failed: "
                  f"{exc.__class__.__name__}")

    post1 = render_post1(results, friday_label)
    blocks = render_post2_blocks(results, friday_label)
    if dry_run or not send_telegram:
        print(post1)
        print()
        for block in blocks:
            print(block)
            print()
    else:
        bot_token = os.getenv("TELEGRAM_CLAW_BOT", "")
        topic_id = _env_int(LOCAL_DEALS_TOPIC_ENV)
        deliver_reports(bot_token, post1, blocks, topic_id)

    if failures and len(failures) < len(active):
        return 1
    if failures:
        return 2
    return 0
