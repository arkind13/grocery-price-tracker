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
    comments = str(row[9]).strip() if len(row) > 9 else ""
    return {"row": sheet_row, "name": name, "prices": prices,
            "comments": comments, "code": code}


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


_STRIP_TOKENS = ("halal", "non", "and", "compare", "vs", "versus",
                 "woolworths", "woolies")


def _query_tokens(query: str) -> list:
    """Product tokens of a query: lowercased alphanumeric words minus
    the halal/non/comparison filler tokens and the retailer brand
    words (a brand word never picks or rejects a product row)."""
    return [t for t in re.findall(r"[a-z0-9]+", str(query or "").lower())
            if t not in _STRIP_TOKENS]


def _fold(token: str) -> str:
    """Light plural fold — one word, both directions. tomato/tomatoes,
    berry/berries, box/boxes, hero/heroes, thigh/thighs, kg/kgs."""
    t = token
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 4 and t.endswith(
            ("shes", "ches", "xes", "zes", "ses", "oes")):
        return t[:-2]
    if len(t) > 2 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _stems(text: str) -> set:
    """Plural-folded token stems of a name or query (word tokens,
    brand/filler words already excluded by the caller's tokeniser when
    needed)."""
    return {_fold(t) for t in re.findall(r"[a-z0-9]+",
                                         str(text or "").lower())}


def _name_has_all(name_lower: str, tokens: list) -> bool:
    """Word-boundary-safe 'contains EVERY token' (subcategory.py
    discipline), plural-folded on BOTH sides — 'Tomatos' finds
    'Tomatoes', 'Choko' finds 'Chokos', 'thigh' finds 'Thighs'."""
    name_stems = _stems(name_lower)
    return all(_fold(t) in name_stems for t in tokens)


def _best_token_row(rows: list, tokens: list):
    """The row whose name is CLOSEST to the query tokens: every query
    token must be present (plural-folded); ranking = fewest unmatched
    name tokens, then the shorter name, then sheet order. This — never
    sheet order alone — picks the row whose code a reply cites
    (2026-09-11 fix: the butchery sort put cousin rows first in sheet
    order, so 'lamb necks' headed with the Fillet row [YTB] instead of
    the matched Sliced Neck [YCQ])."""
    if not tokens:
        return None
    qstems = {_fold(t) for t in tokens}
    best = None
    best_key = None
    for master in rows:
        stems = _stems(str(master["name"] or ""))
        if not qstems <= stems:
            continue
        diff = len(stems - qstems)
        ntok = len(stems)
        key = (diff, ntok)
        if best is None or key < best_key:
            best, best_key = master, key
    return best


def _size_split(text: str) -> tuple:
    """text -> (pack kg, name tokens with the size phrase removed).

    The size phrase is cut as a SPAN, not a token, so '1.8kg'
    (tokenised '1' + '8kg') never leaks a stray number token into a
    name match. Returns (None, tokens) when no size is stated."""
    text = str(text or "").lower()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kgs?\b", text)
    scale = 1.0
    if m is None:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*g\b", text)
        scale = 0.001
    if m is None:
        return None, _query_tokens(text)
    kg = float(m.group(1).replace(",", ".")) * scale
    rest = text[:m.start()] + " " + text[m.end():]
    return kg, _query_tokens(rest)


def _pack_kg(text: str) -> float | None:
    """Pack size in kg parsed from text ('500g' -> 0.5, '(5KG)' -> 5).

    Needs a NUMBER before the unit, so a bare '/kg' price marker never
    matches. Returns None when no weight is stated."""
    text = str(text or "").lower()
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*kgs?\b", text)
    if match:
        return float(match.group(1).replace(",", "."))
    match = re.search(r"(\d+(?:\.\d+)?)\s*g\b", text)
    if match:
        return float(match.group(1)) / 1000.0
    return None


def _fmt_kg(kg: float) -> str:
    """0.5 -> '500g', 5.0 -> '5kg'."""
    return f"{kg * 1000:.0f}g" if kg < 1 else f"{kg:g}kg"


def _pack_master_hit(query: str, master_rows: list, meat: bool):
    """Pack-presented master row matching a name+size-token query.

    2026-09-11 fix (item_exec_2026-09-11_1106.csv): 'halal lebanese
    kofta 4kg' answered bare 'Not tracked' because 'kofta' (like
    'tenderloin', 'chuck') is not a meat term, so the §8 row-3
    halal-local fallback never ran and the exact-name match missed
    the row's '– (4kg)' decoration.

    Rule: the query's size token (kg/g) equals the row's pack size
    (col C, else the name) AND every other query token appears in
    the row name (word-boundary). An exact token-SET match wins over
    containment so 'lamb mince 5kg' takes 'Halal Lamb Mince – (5kg)'
    [WHA], not 'Halal Lean Lamb Mince – (5kg)' [ZDA]. Meat queries
    still resolve through halal-named rows only (spec §5)."""
    kg, tokens = _size_split(query)
    if kg is None or not tokens:
        return None
    token_set = set(tokens)
    equal = contains = None
    for master in master_rows:
        name = str(master["name"] or "")
        low = name.lower()
        if meat and "halal" not in low:
            continue
        row_kg = _pack_kg(master["size"] or name)
        if row_kg is None or row_kg != kg:
            continue
        if not _name_has_all(low, tokens):
            continue
        if contains is None:
            contains = master
        if equal is None and set(_size_split(low)[1]) == token_set:
            equal = master
            break
    return equal or contains


def _non_halal_twin(query: str, master_rows: list,
                    exclude_code: str | None = None) -> list:
    """Plain (non-halal) Woolworths master rows matching a MEAT query.

    Match rule (binding): strip the tokens 'halal'/'non'/'and' (+ the
    comparison fillers 'compare'/'vs'/'versus' and the retailer brand
    words) from the query; a plain DOMAIN row matches iff its
    normalized name contains EVERY remaining query token
    (word-boundary-safe — the subcategory.py discipline), its name
    does NOT contain 'halal', and it is not the halal row already
    answering. `exclude_code` drops the row that IS the answer (a
    tracked plain-row hit must never twin itself). Returns [{'name',
    'state': 'priced'|'gone'|'na', 'value': float|str|None, 'kg':
    float|None}] — the row set the RENDERER shows; no other consumer
    exists.

    Spec §18 A4: reads master_rows ONLY (never Local_Deals — locals
    are always the halal side) and never consults the answering halal
    row's col D. Blank-D plain rows carry no price state → omitted.
    'kg' = pack size from col C (fallback: the row name) so the
    renderer can show the per-kg equivalent of a priced twin.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return []
    twins: list = []
    for master in master_rows:
        name = str(master["name"] or "").lower()
        if "halal" in name or not _is_domain_row(master):
            continue
        if exclude_code and master["code"] == exclude_code:
            continue
        if not _name_has_all(name, tokens):
            continue
        if master["gone"]:
            twins.append({"name": master["name"], "state": "gone",
                          "value": None, "kg": None})
        elif master["na_marker"]:
            twins.append({"name": master["name"], "state": "na",
                          "value": master["na_marker"], "kg": None})
        elif master["ww_num"] is not None:
            twins.append({
                "name": master["name"], "state": "priced",
                "value": master["ww_num"],
                "kg": _pack_kg(master["size"] or master["name"])})
    return twins


def _ld_quotes(ld: dict) -> list:
    """One LD row -> per-shop quote records with unit info.

    The unit marker is the LD NAME suffix (sheet convention): '/kg' =
    the price IS per kg; '/ea' = per pack (pack size parsed from the
    name, e.g. '(5KG)'); no suffix = bare pack price. 'per_kg' makes a
    /kg quote and a 5kg pack comparable (the sheet-wide unit rule)."""
    name = str(ld["name"] or "")
    low = name.strip().lower()
    if low.endswith("/kg"):
        unit, pack = "kg", None
    elif low.endswith("/ea"):
        unit, pack = "ea", _pack_kg(name)
    else:
        unit, pack = "", None
    out: list = []
    for shop, (price, kind) in sorted(ld["prices"].items()):
        if unit == "kg":
            per_kg = price
        elif unit == "ea" and pack:
            per_kg = round(price / pack, 2)
        else:
            per_kg = None
        out.append({"shop": shop, "price": price, "kind": kind,
                    "unit": unit, "pack": pack, "per_kg": per_kg,
                    "note": _shop_note(ld.get("comments", ""), shop)})
    return out


def _shop_note(comments: str, shop: str) -> str:
    """The shop's own Comments segment, tag stripped ('multi buy 2kg
    for $29.99') — rendered next to that shop's price so multibuy
    TERMS are visible in the reply, not just '(special)'."""
    from core.local_deals import _shop_key_for_tag
    note = ""
    for seg in str(comments or "").split(";"):
        seg = seg.strip()
        m = re.match(r"^\[([A-Za-z]+)\]\s*(.+)$", seg)
        if m and _shop_key_for_tag(m.group(1).upper()) == shop:
            note = m.group(2).strip()
    return note


def _quotes_and_best(rows: list) -> tuple:
    """Quote records for LD rows + the winner across them.

    Winner rule: prefer quotes with a computable $/kg (units compare
    fairly); fall back to the raw cheapest when none carries a unit."""
    quotes = [q for ld in rows for q in _ld_quotes(ld)]
    priced = [q for q in quotes if q["per_kg"] is not None]
    if priced:
        best_q = min(priced, key=lambda q: q["per_kg"])
        label = f"${best_q['per_kg']:.2f}/kg"
    elif quotes:
        best_q = min(quotes, key=lambda q: q["price"])
        label = None
    else:
        best_q, label = None, None
    return quotes, best_q, label


_FILLER_RE = re.compile(
    r"^\s*(?:what(?:'s| is|s)\s+)?(?:the\s+)?(?:price|cost)\s+"
    r"(?:of|for)\s+"
    r"|^\s*how\s+much\s+(?:is|are|for)\s+"
    r"|^\s*(?:current|today's|todays)\s+price\s+(?:of|for)\s+",
    re.I)
_TRAILER_RE = re.compile(r"\s*(?:please|thanks)\s*[?.!]*\s*$", re.I)


def _strip_fillers(query: str) -> str:
    """Natural-language price fillers off the front ("price of goat
    curry" → "goat curry", "how much is halal lamb mince" → "halal
    lamb mince") and politeness off the back. 2026-09-11 fix: without
    this the filler tokens matched NO row name, so a meat query fell
    into the unfiltered locals pool — a full-sheet dump under a false
    cluster header (run-2 defect D2)."""
    q = str(query or "").strip()
    for _ in range(3):                      # stacked fillers
        stripped = _FILLER_RE.sub("", q, count=1).strip()
        if stripped == q or not stripped:
            break
        q = stripped
    return _TRAILER_RE.sub("", q).strip() or str(query or "").strip()


def _plain_master_hit(tokens: list, master_rows: list):
    """Plain (non-halal) domain row a MEAT query explicitly names.

    §8 row 1: a query that names the Woolworths product itself
    ("Woolworths Beef Mince 500g") must answer that row's tracked
    class — never the halal locals pool. Gated: the raw query must
    carry a retailer brand word, at least two product tokens must
    match, and the row must not be halal-named."""
    if len(tokens) < 2:
        return None
    candidates = [m for m in master_rows
                  if "halal" not in str(m["name"] or "").lower()
                  and _is_domain_row(m)
                  and _name_has_all(str(m["name"] or "").lower(), tokens)]
    return _best_token_row(candidates, tokens)


def _domain_master_hit(tokens: list, master_rows: list):
    """Order-free, plural-folded master-row match for NON-meat
    queries ('Cauliflowers' → 'Cauliflower', 'Choko' → 'Chokos',
    'R2E2 Mango' → 'Mango R2E2'). A bare single word answers only
    when a candidate wins STRICTLY (a tie between two different
    products — 'apples' across Pink Lady / Granny Smith — stays
    unanswered rather than guessing); 'halal drumsticks' folds to
    one token whose closest row (the /kg VCK row, not the 5kg pack)
    wins by the normal min-diff ranking."""
    if not tokens:
        return None
    candidates = [m for m in master_rows
                  if _is_domain_row(m)
                  and _name_has_all(str(m["name"] or "").lower(), tokens)]
    if not candidates:
        return None
    if len(tokens) < 2 and len(candidates) > 1:
        qstems = {_fold(t) for t in tokens}
        diffs = sorted(len(_stems(str(m["name"] or "")) - qstems)
                       for m in candidates)
        if diffs[0] == diffs[1]:
            return None
    return _best_token_row(candidates, tokens)


def lookup_item_hit(hit: dict, master_rows, ld_rows, twins: list,
                    q: str) -> dict:
    """The §8 answer dict for a RESOLVED master row (status derived
    from the row's own cells; locals from its code-paired LD row)."""
    ld = next((ld for ld in ld_rows
               if ld["code"] and ld["code"] == hit["code"]), None)
    prices = dict(ld["prices"]) if ld else {}
    quotes, best_q, best_label = _quotes_and_best([ld] if ld else [])
    best = ((best_q["shop"], best_q["price"], best_q["kind"])
            if best_q else None)
    base = {"master": hit, "local": prices, "best": best,
            "best_label": best_label, "local_quotes": quotes,
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


def lookup_item(query: str, master_rows, ld_rows) -> dict:
    """Sheet-only lookup per the §8 table. NEVER raises on a miss.

    Match: exact Col A, then exact alias (col J), case-insensitive;
    then a pack-presented row by name+size token ('halal lamb mince
    5kg' -> 'Halal Lamb Mince – (5kg)'); then — meat query naming the
    Woolworths product itself — the plain WW row's tracked class
    (§8 row 1); a MEAT query otherwise resolves through halal-named
    rows only (spec §5); a non-meat query falls to an order-free,
    plural-folded token match ('Cauliflowers' -> 'Cauliflower').
    """
    q = _strip_fillers(str(query or "").strip())
    ql = q.lower()
    meat = is_meat_query(q)
    twins = _non_halal_twin(q, master_rows) if meat else []
    brand_named = any(w in ql for w in ("woolworths", "woolies"))

    def _hit_twins(hit_code: str) -> list:
        # the answering row must never twin itself (§18 A4)
        return (_non_halal_twin(q, master_rows, exclude_code=hit_code)
                if meat else [])

    def _matches(name: str) -> bool:
        low = name.lower()
        if meat:
            # exact halal row, OR the plain WW row the query names
            # verbatim WITH the brand word ('Woolworths Beef Mince
            # 500g' answers GJZ's tracked class, not a locals dump;
            # a brandless 'beef diced' stays halal-scoped — row3b)
            return low == ql and ("halal" in low or brand_named)
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

    if hit is None:
        hit = _pack_master_hit(q, master_rows, meat)

    if hit is None and meat and brand_named and "halal" not in ql:
        # §8 row 1 via an explicit brand naming ('500g Woolworths
        # Beef Mince'): the plain row's own tracked class — a halal-
        # prefixed brand query keeps the halal cluster + twin instead
        hit = _plain_master_hit(_query_tokens(q), master_rows)

    if hit is None and meat:
        # §8 row 3: meat term, no halal master row — fall back to
        # halal-named LOCAL rows (butcher prices + missing-list code).
        # 2026-09-10 user fix: when halal LD rows match the QUERY
        # tokens, pool ONLY those — a 'beef mince' answer must never
        # quote a chicken row. The unfiltered pool survives only as
        # the last resort so a meat term never answers empty.
        # NOTE: the pool matches on the query's FULL product tokens —
        # the size token stays, so 'halal lebanese kofta 5kg' can
        # never pool the 4kg row (size-mismatch discipline)
        tokens = _query_tokens(q)
        locals_with = [ld for ld in ld_rows
                       if "halal" in ld["name"].lower() and ld["prices"]]
        matched = [ld for ld in locals_with
                   if _name_has_all(str(ld["name"]).lower(), tokens)]
        pool_rows = matched or locals_with
        if pool_rows:
            prices: dict = {}
            for ld in pool_rows:
                for shop, (price, kind) in ld["prices"].items():
                    prices.setdefault(shop, (price, kind))
            quotes, best_q, best_label = _quotes_and_best(pool_rows)
            best = ((best_q["shop"], best_q["price"], best_q["kind"])
                    if best_q else None)
            # the header code is the MATCHED row's — best token match
            # across the matched LD rows AND the halal master rows,
            # never 'first row in sheet order' (run-2 D3: cousin
            # codes; lamb-necks regression: [YTB] for [YCQ]). With no
            # matched row at all the unfiltered pool answers WITHOUT
            # a code — a false 'missing list [XJA]' header on a
            # full-sheet dump is worse than an honest one.
            code_row = (_best_token_row(matched, tokens) if matched
                        else None)
            if code_row is None:
                halal_masters = [m for m in master_rows
                                 if "halal" in str(m["name"] or "")
                                 .lower()]
                code_row = _best_token_row(halal_masters, tokens)
            return {"status": "meat-local-only", "master": None,
                    "local": prices, "best": best,
                    "best_label": best_label,
                    "local_quotes": quotes,
                    "code": code_row["code"] if code_row else "",
                    "non_halal_twins": twins,
                    "query": q}

    if hit is not None:
        return lookup_item_hit(hit, master_rows, ld_rows,
                               _hit_twins(hit["code"]), q)

    if hit is None and not meat:
        # realistic non-meat forms: plural ('Cauliflowers'),
        # singular ('Choko' on 'Chokos'), noun-first ('R2E2 Mango').
        # FULL product tokens — the size token stays, so a size
        # mismatch ('… 5kg' vs a 4kg row) can never route
        hit = _domain_master_hit(_query_tokens(q), master_rows)
        if hit is not None:
            return lookup_item_hit(hit, master_rows, ld_rows, [], q)

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


def _quote_price_text(q: dict) -> str:
    """One quote's price text with its unit basis ('$15.99/kg',
    '$64.99 / 5kg pack = $13.00/kg', '$8.99/ea' or a bare '$8.99')."""
    if q["unit"] == "kg":
        return f"${q['price']:.2f}/kg"
    if q["unit"] == "ea" and q["pack"]:
        return (f"${q['price']:.2f} / {_fmt_kg(q['pack'])} pack"
                f" = ${q['per_kg']:.2f}/kg")
    if q["unit"] == "ea":
        return f"${q['price']:.2f}/ea"
    return f"${q['price']:.2f}"


def _note_text(note: str) -> str:
    """Note suffix, 'multi buy …' shortened to 'min order …'.

    A standalone helper (container parity with the 2026-09-11 03:22
    VPS hot-patch): py3.11 rejects PEP 701 f-strings, so the re.sub
    must not sit inside an f-string expression."""
    import re
    return " · " + re.sub(r"^multi buy\b", "min order", note, count=1)


def _local_lines(result: dict) -> list:
    """Aligned per-shop price lines (kit: aligned price columns).
    Quote records (local_quotes) carry the sheet's unit markers —
    '/kg' prices show per kg and '/ea' packs show their per-kg rate —
    so a /kg quote and a 5kg pack compare fairly on screen."""
    from core.telegram_format import _cells

    quotes = result.get("local_quotes") or []
    if quotes:
        ordered = sorted(quotes, key=lambda q: (
            q["per_kg"] is None, q["per_kg"] or q["price"], q["price"]))
        tagged = [(f"{_SHOP_ICONS.get(q['shop'], '·')} "
                   f"{_shop_label(q['shop'])}",
                   _quote_price_text(q)
                   + {"special": " (special)", "permanent": ""}[
                       q["kind"]]
                   + (_note_text(q["note"]) if q.get("note") else ""))
                  for q in ordered]
    else:
        entries = sorted(result["local"].items(),
                         key=lambda kv: kv[1][0])
        tagged = [(f"{_SHOP_ICONS.get(shop, '·')} {_shop_label(shop)}",
                   f"${price:.2f}"
                   + {"special": " (special)", "permanent": ""}[kind])
                  for shop, (price, kind) in entries]
    width = max((_cells(label) for label, _ in tagged), default=0)
    lines: list = []
    for label, price_text in tagged:
        pad = " " * max(0, width - _cells(label))
        lines.append(f"  {label}{pad}  {price_text}")
    return lines


def _twin_lines(result: dict) -> list:
    """Non-halal twin display lines (spec §18 A4) — one per twin, the
    EXACT test.md format. A priced twin goes through the EXISTING WW
    display-discount engine (§5); the twin dict carries no brand, so
    home-brand detection runs on the row name alone (the engine's
    blank-brand rule). A priced twin with a stated pack size also
    shows its per-kg rate — a 500g Wool pack must never be compared
    against the butchers' /kg quotes unit-blind (user rule 2026-09-10)."""
    from core.woolworths_discounts import discounted_woolworths_price, \
        format_discounted_price, is_woolworths_home_brand, \
        TEAM_DISCOUNT_ENABLED

    lines: list = []
    for twin in result.get("non_halal_twins") or []:
        name = twin["name"]
        if twin["state"] == "priced":
            home = is_woolworths_home_brand(name, "")
            price = format_discounted_price(twin["value"], home)
            final = (discounted_woolworths_price(twin["value"], home)[
                "final"] if TEAM_DISCOUNT_ENABLED else twin["value"])
            per_kg = (f" · {_fmt_kg(twin['kg'])} = "
                      f"${final / twin['kg']:.2f}/kg"
                      if twin.get("kg") else "")
            lines.append(f"also at Woolworths (non-halal): {price}"
                         f"{per_kg} — {name}")
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
    from core.woolworths_discounts import discounted_woolworths_price, \
        format_discounted_price, is_woolworths_home_brand, \
        TEAM_DISCOUNT_ENABLED

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
        # per-kg basis for the halal Wool price too — the butchers'
        # quotes are /kg (user unit rule 2026-09-10)
        kg = _pack_kg(master["size"] or master["name"])
        if kg:
            final = (discounted_woolworths_price(master["ww_num"],
                                                 home)["final"]
                     if TEAM_DISCOUNT_ENABLED else master["ww_num"])
            size_txt = master["size"] or _fmt_kg(kg)
            ww_price += f" · {size_txt} = ${final / kg:.2f}/kg"
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
        # a matched row's code leads the missing-list line; the
        # unfiltered last-resort pool answers WITHOUT one — never a
        # false '[XJA]' header on rows the query never named
        lines.append("Not tracked at Woolworths — missing list "
                     f"[{result['code']}]" if result.get("code")
                     else "Not tracked at Woolworths")
    elif status == "out-of-domain":
        return "Not tracked — outside local-shop domains"
    else:
        return "Not tracked" + (
            f" [{result['code']}]" if result.get("code") else "")

    lines.extend(_local_lines(result))
    best = result.get("best")
    if best:
        # unit-normalised winner when the quotes carry $/kg, else the
        # legacy raw-price badge
        winner = result.get("best_label") or f"${best[1]:.2f}"
        lines.append(f"  {winner_line(winner, _shop_label(best[0]))}")
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
