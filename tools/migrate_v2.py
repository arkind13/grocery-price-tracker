"""One-shot v2 sheet migration (Round 2). Subcommands:
  preview           — G1/G2/G3 previews (read-only)
  apply-stay-leave  — G1 outcome: Archive tab + retire rows
  apply-columns     — G2 outcome: drop E,F,J,K,L,N
  apply-parity      — G3 outcome: halal renames + blank master rows +
                      Local_Deals col K + positional alignment
  audit             — parity audit via tools/parity_audit.audit

Grid helpers are PURE (offline-testable); only main() touches the
sheet. The apply-* verbs ask nothing (the SESSION owns the USER GATES)
and verify their own post-state. Idempotent: a second apply run makes
zero changes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.local_deals import (                     # noqa: E402
    BUTCHERY_DOMAIN, PRODUCE_SUBCATEGORIES, SECTION_ORDER,
    _base_name, canonical_key,
)
from core.subcategory import normalize_subcategory  # noqa: E402

MASTER_TAB = "Products_Master"
LD_TAB = "Local_Deals"
ARCHIVE_TAB = "Archive"

# Products_Master layout v2 (spec §3.1) — the EXACT post-G2 header.
NEW_MASTER_HEADERS = [
    "Product_Name", "Category", "Size", "Woolworths_Price",
    "Brand_Type", "Last_Updated", "Search_Keyword_Woolworths",
    "Woolworths_Specials", "Rewards_Points", "Keywords",
    "Sub_Category", "Item_Code", "Preferred",
]

# G2: drop 0-based indices E,F,J,K,L,N (Coles/Aldi columns).
DROP_INDICES_0BASED = (4, 5, 9, 10, 11, 13)
# G2 apply order: 1-based, strictly descending (N, L, K, J, F, E).
DROP_COLUMNS_1BASED_DESC = (14, 12, 11, 10, 6, 5)

# Pre-G2 (19-col) fixed indices.
OLD_SUBCATEGORY_IDX = 16       # col Q
OLD_ITEM_CODE_IDX = 17         # col R
# Post-G2 (13-col) fixed indices.
NEW_SUBCATEGORY_IDX = 10       # col K
NEW_ITEM_CODE_IDX = 11         # col L
# Local_Deals v2.1 layout: Item_Code in col K (0-based idx 10).
LD_CODE_IDX = 10

# Produce-adjacent labels OUTSIDE the strict keep sets — the user
# rules on these at G1 (default: NOT kept).
BORDERLINE = {"lettuce", "coriander", "greek salad"}

FRUIT_DOMAIN_LABEL = "fruit & veg"   # the fruit-shop domain label
BUTCHERY_DOMAIN_LABEL = "butchery"   # the butchery domain label

CODE_SEED = "migrate-v2"       # deterministic code generation


# ---------------------------------------------------------------------------
# Pure grid helpers
# ---------------------------------------------------------------------------

def _cell(row: list, idx: int) -> str:
    return str(row[idx]).strip() if len(row) > idx else ""


def _header(grid: list) -> list:
    """Grid row 0 as stripped strings (header cells are NOT rows)."""
    return [str(c).strip() for c in (grid[0] if grid else [])]


def stay_leave(master_grid: list) -> dict:
    """G1 classification (Q1 keep rule) off the 19-col master grid.

    Keep iff normalize_subcategory(col Q) ∈ BUTCHERY_DOMAIN ∪
    PRODUCE_SUBCATEGORIES. BORDERLINE labels are listed separately
    (default: NOT kept unless the user moves them). Returns
    {'keep': [...], 'leave': [...], 'borderline': [...]} of row dicts
    {row, name, code, sub_category} (row = 1-based sheet row).
    """
    header = master_grid[0] if master_grid else []
    if len(header) < 19:
        raise ValueError(
            "stay_leave expects the 19-column pre-migration master "
            f"grid (got {len(header)} columns) — G1 runs BEFORE "
            "apply-columns")
    keep_sets = BUTCHERY_DOMAIN | PRODUCE_SUBCATEGORIES
    out = {"keep": [], "leave": [], "borderline": []}
    for i, row in enumerate(master_grid[1:], start=2):
        name = _cell(row, 0)
        if not name:
            continue
        sub = normalize_subcategory(_cell(row, OLD_SUBCATEGORY_IDX))
        entry = {"row": i, "name": name,
                 "code": _cell(row, OLD_ITEM_CODE_IDX),
                 "sub_category": sub}
        if sub in keep_sets:
            out["keep"].append(entry)
        elif sub in BORDERLINE:
            out["borderline"].append(entry)
        else:
            out["leave"].append(entry)
    return out


def build_archive_grid(master_grid: list) -> list:
    """Verbatim FULL 19-column copy incl. header (spec §3.4)."""
    if master_grid and len(master_grid[0]) < 19:
        raise ValueError("archive expects the 19-column master grid")
    return [(list(row) + [""] * 19)[:19] for row in master_grid]


def drop_columns(master_grid: list) -> list:
    """Remove 0-based indices [4, 5, 9, 10, 11, 13] (E,F,J,K,L,N).

    Asserts the result header equals the 13 headers of spec §3.1 in
    order; raises (does NOT write) on any mismatch.
    """
    drop = set(DROP_INDICES_0BASED)
    out = [[c for i, c in enumerate(row) if i not in drop]
           for row in master_grid]
    header = _header(out)
    if header != NEW_MASTER_HEADERS:
        raise ValueError(
            f"dropped header mismatch:\n  got      {header}\n"
            f"  expected {NEW_MASTER_HEADERS}")
    return out


def plan_halal_renames(ld_grid: list) -> list:
    """BUTCHERY-section item rows whose base name lacks 'halal'
    (case-insensitive) → (row_idx, old_name, 'Halal ' + old_name).

    row_idx is the 0-based GRID index. FRUITS/OTHER rows untouched
    (spec §5); structural rows (header / validity / titles) skipped.
    """
    renames: list = []
    section = ""
    for i, row in enumerate(ld_grid):
        first = _cell(row, 0)
        if i == 0 or first == "Prices valid until":
            continue
        if first in SECTION_ORDER:
            section = first
            continue
        if section != "BUTCHERY" or not first:
            continue
        if "halal" not in _base_name(first).lower():
            renames.append((i, first, f"Halal {first}"))
    return renames


def _apply_renames(ld_grid: list, renames: list) -> list:
    """Copy of ld_grid with the rename plan applied to Col A."""
    grid = [list(row) for row in ld_grid]
    for idx, _old, new in renames:
        row = grid[idx]
        row[0] = new
        while len(row) < 10:
            row.append("")
    return grid


def _master_code_index(master_grid_13: list) -> dict:
    """canonical_key(_base_name(name)) -> [(grid_idx, code), ...] in
    grid order (canonical-equal master rows group as occurrences)."""
    index: dict = {}
    for i, row in enumerate(master_grid_13[1:], start=1):
        name = _cell(row, 0)
        if not name:
            continue
        key = canonical_key(_base_name(name))
        index.setdefault(key, []).append((i, _cell(row,
                                                   NEW_ITEM_CODE_IDX)))
    return index


def _existing_master_codes(master_grid_13: list) -> set:
    """Every code on the master grid (col L), upper-cased."""
    codes = set()
    for row in master_grid_13[1:]:
        code = _cell(row, NEW_ITEM_CODE_IDX).upper()
        if code:
            codes.add(code)
    return codes


def _new_code_batch(taken: set, n: int) -> list:
    """n new 3-letter codes (A–Z minus I/L/O), unique vs `taken`.

    Uses core.item_codes.generate_codes (the system's own generator,
    seed-deterministic for this migration) PLUS the retired-code
    registry, so a generated code can never collide with a code the
    system has ever assigned (never-reuse rule, D-IC2).
    """
    from core.item_codes import generate_codes, load_registry, \
        retired_codes

    taken = {str(c).upper() for c in taken} | retired_codes(
        load_registry())
    return generate_codes(taken, n, seed=CODE_SEED)


def plan_new_master_rows(ld_grid: list, master_grid_13: list) -> list:
    """Unpaired LD item rows → new blank master row plans.

    A row is unpaired when NO master row's canonical base name matches
    (core.local_deals.canonical_key + _base_name). Names are matched
    POST-halal-rename (rename-first order — a plain non-halal master
    row never pairs with a butchery item, Q11).

    Returns [{'name', 'code', 'subcategory', 'ld_row'}] — name gets
    the 'Halal ' prefix for BUTCHERY-section rows only (unit suffix
    stripped: master names never carry ' /kg'/' /ea'); subcategory is
    the item's domain label ('fruit & veg' / 'butchery'); codes come
    from _new_code_batch (unique vs all existing master codes + the
    retired registry).
    """
    renames = plan_halal_renames(ld_grid)
    ld_renamed = _apply_renames(ld_grid, renames)
    master_index = _master_code_index(master_grid_13)
    taken = _existing_master_codes(master_grid_13)

    # First pass: find unpaired rows (in tab order).
    unpaired: list = []
    section = ""
    for i, row in enumerate(ld_renamed):
        first = _cell(row, 0)
        if i == 0 or first == "Prices valid until":
            continue
        if first in SECTION_ORDER:
            section = first
            continue
        if not first:
            continue                     # structural / Wool-only mirror
        if canonical_key(_base_name(first)) in master_index:
            continue
        unpaired.append((i, first, section))

    codes = _new_code_batch(taken, len(unpaired))
    planned: list = []
    for (grid_idx, name, sec), code in zip(unpaired, codes):
        base = _base_name(name)
        if sec == "BUTCHERY":
            sub = BUTCHERY_DOMAIN_LABEL
            # the rename plan already prefixed the LD name — never
            # double it; a bare (unrenamed) halal name stays as-is
            out_name = base if base.lower().startswith("halal ") \
                else f"Halal {base}"
        else:
            sub = FRUIT_DOMAIN_LABEL
            out_name = base
        planned.append({"name": out_name, "code": code,
                        "subcategory": sub, "ld_row": grid_idx})
    return planned


def ld_row_code_map(ld_grid: list, master_grid_13: list,
                    planned: list) -> dict:
    """LD grid idx → (Item_Code, 'matched' | 'new') for ITEM rows.

    Matched rows carry the matched master row's code; created rows
    carry their planned code. Canonical-equal rows pair by
    OCCURRENCE order (the k-th LD row of a key with the k-th master
    row of the same key) — never first-hit aliasing, which would
    double-assign one master row and orphan its twin (the Lamb Curry
    crash-resume defect). Structural rows are absent.
    """
    renames = plan_halal_renames(ld_grid)
    ld_renamed = _apply_renames(ld_grid, renames)
    master_index = _master_code_index(master_grid_13)
    consumed: dict = {}
    code_by_ld_row = {p["ld_row"]: (p["code"], "new")
                      for p in planned}
    section = ""
    for i, row in enumerate(ld_renamed):
        first = _cell(row, 0)
        if i == 0 or first == "Prices valid until":
            continue
        if first in SECTION_ORDER:
            section = first
            continue
        if not first:
            continue                     # structural / Wool-only mirror
        occurrences = master_index.get(
            canonical_key(_base_name(first)))
        if occurrences:
            k = consumed.get(occurrences[0][0], 0)
            if k < len(occurrences):
                code_by_ld_row[i] = (occurrences[k][1], "matched")
                consumed[occurrences[0][0]] = k + 1
    return code_by_ld_row


def blank_master_row(name: str, code: str, subcategory: str) -> list:
    """13-col blank master row: name, Item_Code, Sub_Category only —
    D (price) and G (keyword) stay BLANK (spec §4.2: code writes NO
    prices, NO keywords)."""
    row = [""] * 13
    row[0] = name
    row[NEW_SUBCATEGORY_IDX] = subcategory
    row[NEW_ITEM_CODE_IDX] = code
    return row


def align_grids(master_grid_13: list,
                ld_grid_11: list) -> tuple:
    """Positional alignment (spec §3.3).

    Unified order = LD item rows in tab order (LD section rows
    FRUITS/BUTCHERY/OTHER preserved on the LD side only), then
    Wool-only master rows appended at the END — each mirrored by a
    BLANK LD item row (Col A empty, code in col K). Master data row N
    ↔ LD item row N; master carries NO section rows.

    Returns (master_out, ld_out). Raises on an LD item code with no
    master counterpart (never writes).
    """
    master_by_code: dict = {}
    master_order: list = []
    for row in master_grid_13[1:]:
        name = _cell(row, 0)
        if not name:
            continue
        code = _cell(row, NEW_ITEM_CODE_IDX).upper()
        if not code:
            raise ValueError(
                f"master row {name!r} has no Item_Code — migration "
                "requires every row coded")
        if code in master_by_code:
            raise ValueError(f"duplicate master Item_Code {code}")
        master_by_code[code] = list(row)[:13] + [""] * max(
            0, 13 - len(row))
        master_order.append(code)

    header = (list(ld_grid_11[0]) + [""] * 11)[:11]
    validity = None
    if len(ld_grid_11) > 1 and _cell(ld_grid_11[1], 0) == \
            "Prices valid until":
        validity = (list(ld_grid_11[1]) + [""] * 11)[:11]

    master_out: list = [list(NEW_MASTER_HEADERS)]
    ld_out: list = [header]
    if validity is not None:
        ld_out.append(validity)

    used: set = set()
    emitted: set = set()
    section = ""
    for i, row in enumerate(ld_grid_11):
        first = _cell(row, 0)
        if i == 0 or first == "Prices valid until":
            continue
        if first in SECTION_ORDER:
            section = first
            ld_out.append((list(row) + [""] * 11)[:11])
            continue
        if not first and not _cell(row, LD_CODE_IDX):
            continue
        code = _cell(row, LD_CODE_IDX).upper()
        if code in emitted:
            raise ValueError(
                f"Local_Deals rows carry duplicate Item_Code {code} "
                "— codes are permanent unique IDs (spec §3.1); "
                "resolve the duplicate before aligning")
        master_row = master_by_code.get(code)
        if master_row is None:
            raise ValueError(
                f"Local_Deals row {i + 1} ({first!r}) carries code "
                f"{code or '—'} with no master counterpart")
        master_out.append(master_row)
        ld_out.append((list(row) + [""] * 11)[:11])
        used.add(code)
        emitted.add(code)

    # Wool-only master rows -> END of both tabs (blank LD mirror).
    for code in master_order:
        if code in used:
            continue
        master_out.append(master_by_code[code])
        blank = [""] * 11
        blank[LD_CODE_IDX] = code
        ld_out.append(blank)
    return master_out, ld_out


# ---------------------------------------------------------------------------
# Shared live-sheet plumbing (only these touch the network)
# ---------------------------------------------------------------------------

def _connect():
    from core.sheets_client import connect_spreadsheet
    return connect_spreadsheet()


def _tab(spreadsheet, title: str):
    return spreadsheet.worksheet(title)


def _read_master(spreadsheet) -> list:
    return _tab(spreadsheet, MASTER_TAB).get_all_values() or []


def _read_ld(spreadsheet) -> list:
    return _tab(spreadsheet, LD_TAB).get_all_values() or []


def _pad(grid: list, width: int) -> list:
    return [(list(row) + [""] * width)[:width] for row in grid]


# ---------------------------------------------------------------------------
# G1 apply
# ---------------------------------------------------------------------------

def _delete_row_with_backoff(worksheet, row: int, retries: int = 2) \
        -> None:
    """delete_rows with 429 quota backoff (per-minute write quota)."""
    import time

    for attempt in range(retries + 1):
        try:
            worksheet.delete_rows(row)
            return
        except Exception as exc:                       # noqa: BLE001
            is_429 = "429" in str(exc)
            if not is_429 or attempt == retries:
                raise
            print(f"[G1] write quota hit — backing off 65s "
                  f"({attempt + 1}/{retries})")
            time.sleep(65)


def apply_stay_leave(spreadsheet=None, force_keep=(), force_leave=()
                     ) -> int:
    """G1 outcome: Archive tab + delete the confirmed-LEAVE rows.

    force_keep / force_leave: Item_Codes the user moved between lists
    at the gate. Returns 0 (applied or already applied).
    """
    spreadsheet = spreadsheet or _connect()
    master_ws = _tab(spreadsheet, MASTER_TAB)
    master = _read_master(spreadsheet)
    ruling = stay_leave(master)
    keep_rows = {e["row"] for e in ruling["keep"]}
    move_to_keep = {c.strip().upper() for c in force_keep if c.strip()}
    move_to_leave = {c.strip().upper() for c in force_leave
                     if c.strip()}
    all_entries = (ruling["keep"] + ruling["borderline"]
                   + ruling["leave"])

    def _kept(e: dict) -> bool:
        code = e["code"].upper()
        if code in move_to_leave:
            return False
        if code in move_to_keep:
            return True
        return e["row"] in keep_rows

    kept = [e for e in all_entries if _kept(e)]
    gone = [e for e in all_entries if not _kept(e)]

    archive_ws = None
    wrote_archive = False
    try:
        archive_ws = _tab(spreadsheet, ARCHIVE_TAB)
    except Exception:                                  # noqa: BLE001
        archive_ws = spreadsheet.add_worksheet(
            ARCHIVE_TAB, rows=len(master), cols=19)
        archive_ws.update(values=build_archive_grid(master),
                          range_name=f"A1:S{len(master)}")
        wrote_archive = True

    if gone:
        import time
        for entry in sorted(gone, key=lambda e: -e["row"]):
            _delete_row_with_backoff(master_ws, entry["row"])
            time.sleep(1.05)      # sheets write quota: 60/min per user
    after = _read_master(spreadsheet)
    data_rows = sum(1 for row in after[1:] if _cell(row, 0))
    ok = (data_rows == len(kept)
          and all(_cell(row, 0) for row in after[1:]))
    print(f"[G1] archive: "
          f"{'created' if wrote_archive else 'already present'} "
          f"({ARCHIVE_TAB})")
    print(f"[G1] deleted {len(gone)} retired row(s); "
          f"master now {len(after)} rows x "
          f"{max((len(r) for r in after), default=0)} cols "
          f"= header + {data_rows} confirmed keeps "
          f"(+{len(move_to_keep)} user-kept, "
          f"-{len(move_to_leave)} user-retired)")
    if not ok:
        print(f"[G1] VERIFY FAILED: expected {len(kept)} data rows, "
              f"found {data_rows}")
        return 1
    print(f"[G1] VERIFIED: master = header + {data_rows} keeps")
    return 0


# ---------------------------------------------------------------------------
# G2 apply
# ---------------------------------------------------------------------------

def apply_columns(spreadsheet=None) -> int:
    """G2 outcome: drop E,F,J,K,L,N (descending N,L,K,J,F,E)."""
    spreadsheet = spreadsheet or _connect()
    ws = _tab(spreadsheet, MASTER_TAB)
    master = _read_master(spreadsheet)
    header = _header(master)
    if header == NEW_MASTER_HEADERS:
        print("[G2] already applied (header is the 13-col v2 layout)")
        return 0
    if len(header) < 19:
        print(f"[G2] ABORT: unexpected master width {len(header)} "
              "(expected 19 pre-migration columns)")
        return 1
    for col in DROP_COLUMNS_1BASED_DESC:
        ws.delete_columns(col)
    after = _read_master(spreadsheet)
    got = _header(after)
    if got != NEW_MASTER_HEADERS:
        print(f"[G2] VERIFY FAILED: header now {got}")
        return 1
    print(f"[G2] deleted columns {DROP_COLUMNS_1BASED_DESC} "
          "(N, L, K, J, F, E)")
    print(f"[G2] VERIFIED: {len(after)} rows x "
          f"{max((len(r) for r in after), default=0)} cols — "
          "header matches spec §3.1 exactly")
    return 0


# ---------------------------------------------------------------------------
# G3 apply
# ---------------------------------------------------------------------------

def build_parity_plan(master_grid_13: list, ld_grid: list) -> dict:
    """Everything G3 will write, computed PURELY (preview == apply)."""
    renames = plan_halal_renames(ld_grid)
    ld_renamed = _apply_renames(ld_grid, renames)
    planned = plan_new_master_rows(ld_grid, master_grid_13)
    code_map = ld_row_code_map(ld_grid, master_grid_13, planned)

    ld11 = _pad(ld_renamed, 11)
    ld11[0][10] = "Item_Code"
    for idx, (code, _kind) in code_map.items():
        ld11[idx][10] = code
    master_padded = _pad(master_grid_13, 13)
    master_with_new = master_padded + [
        blank_master_row(p["name"], p["code"], p["subcategory"])
        for p in planned]
    master_final, ld_final = align_grids(master_with_new, ld11)
    return {"renames": renames, "planned": planned,
            "code_map": code_map, "master_final": master_final,
            "ld_final": ld_final}


def apply_parity(spreadsheet=None) -> int:
    """G3 outcome, in order: S4 renames → blank master rows → LD col K
    → S7 alignment → audit ALIGNED."""
    from tools.parity_audit import audit, format_report

    spreadsheet = spreadsheet or _connect()
    master_ws = _tab(spreadsheet, MASTER_TAB)
    ld_ws = _tab(spreadsheet, LD_TAB)
    master = _read_master(spreadsheet)
    ld = _read_ld(spreadsheet)

    header = _header(master)
    if header != NEW_MASTER_HEADERS:
        print(f"[G3] ABORT: master header is not the 13-col v2 "
              f"layout — run apply-columns first (got {len(header)} "
              "cols)")
        return 1

    plan = build_parity_plan(master, ld)
    renames = plan["renames"]
    planned = plan["planned"]
    code_map = plan["code_map"]

    if not renames and not planned \
            and _cell(ld[0], 10) == "Item_Code":
        result = audit(_read_master(spreadsheet), _read_ld(spreadsheet))
        if result["status"] == "aligned":
            print("[G3] already applied (audit: ALIGNED) — no changes")
            return 0

    # 1. S4 renames on Local_Deals (BUTCHERY rows only).
    if renames:
        ld_ws.batch_update([
            {"range": f"A{idx + 1}", "values": [[new]]}
            for idx, _old, new in renames])
    print(f"[G3] 1. renames: {len(renames)} BUTCHERY row(s) → "
          "'Halal …'")

    # Codes confirmed into the registry BEFORE any sheet write (the
    # never-reuse contract); generate is seed-deterministic, so the
    # codes here are exactly the planned ones.
    from core.item_codes import confirm_code
    sid = str(getattr(spreadsheet, "id", "") or "")
    final_master_rows = plan["master_final"][1:]
    row_of_code = {_cell(r, NEW_ITEM_CODE_IDX).upper(): n + 2
                   for n, r in enumerate(final_master_rows)}
    for p in planned:
        code = p["code"].upper()
        if code in row_of_code:
            confirm_code(code, row_of_code[code], spreadsheet_id=sid)

    # 2. Blank master rows appended at the bottom.
    if planned:
        start = len(master) + 1                     # 1-based
        new_rows = [blank_master_row(p["name"], p["code"],
                                     p["subcategory"])
                    for p in planned]
        master_ws.update(values=new_rows,
                         range_name=f"A{start}:M{start + len(new_rows) - 1}")
    print(f"[G3] 2. blank master rows appended: {len(planned)} "
          "(name + Item_Code + Sub_Category only)")

    # 3. LD col K: header + the paired master code on every item row.
    # The values API auto-grows ROWS but never COLUMNS — widen the
    # tab grid to 11 first or the K-range write 400s.
    if getattr(ld_ws, "col_count", 11) < 11:
        ld_ws.add_cols(11 - ld_ws.col_count)
    ld11 = _pad(ld, 11)
    ld11[0][10] = "Item_Code"
    for idx, (code, _kind) in code_map.items():
        ld11[idx][10] = code
    ld_ws.update(values=[[row[10]] for row in ld11],
                 range_name=f"K1:K{len(ld11)}")
    print(f"[G3] 3. Local_Deals col K: header + {len(code_map)} "
          "item code(s) backfilled")

    # 4. S7 alignment: one clear() + one update() per tab.
    master_final = plan["master_final"]
    ld_final = plan["ld_final"]
    master_ws.clear()
    master_ws.freeze(rows=1)
    master_ws.update(values=master_final,
                     range_name=f"A1:M{len(master_final)}")
    ld_ws.clear()
    ld_ws.freeze(rows=2)
    ld_ws.update(values=ld_final,
                 range_name=f"A1:K{len(ld_final)}")
    from tools.parity_audit import is_ld_item_row
    ld_item_count = sum(1 for i, r in enumerate(ld_final)
                        if is_ld_item_row(i, r))
    print(f"[G3] 4. aligned: master {len(master_final) - 1} data "
          f"rows <-> {ld_item_count} LD item rows "
          "(LD structural rows exempt)")

    # 5. audit → must print ALIGNED.
    result = audit(_read_master(spreadsheet), _read_ld(spreadsheet))
    print(f"[G3] 5. audit: {format_report(result)}")
    return 0 if result["status"] == "aligned" else 1


# ---------------------------------------------------------------------------
# Previews + audit
# ---------------------------------------------------------------------------

def _fmt_g1(ruling: dict, force_keep, force_leave) -> str:
    lines: list = []
    keep_sets = BUTCHERY_DOMAIN | PRODUCE_SUBCATEGORIES
    move_to_keep = {c.strip().upper() for c in force_keep if c.strip()}
    move_to_leave = {c.strip().upper() for c in force_leave
                     if c.strip()}

    def _mark(e: dict) -> str:
        code = e["code"].upper()
        if code in move_to_keep:
            return "KEEP (user ruling)"
        if code in move_to_leave:
            return "LEAVE (user ruling)"
        return ""

    kept = [e for e in ruling["keep"]
            if e["code"].upper() not in move_to_leave]
    kept += [e for e in ruling["borderline"]
             if e["code"].upper() in move_to_keep]
    border = [e for e in ruling["borderline"]
              if e["code"].upper() not in move_to_keep]
    left = [e for e in ruling["leave"]
            if e["code"].upper() not in move_to_keep]
    left += [e for e in ruling["keep"]
             if e["code"].upper() in move_to_leave]

    lines.append(f"KEEP ({len(kept)}) — stay (sub-category ∈ "
                 f"butchery/produce sets):")
    for e in kept:
        note = _mark(e)
        lines.append(f"  row {e['row']:>3}  {e['code']:<4} "
                     f"{e['name'][:44]:<44} [{e['sub_category']}]"
                     + (f"  ← {note}" if note else ""))
    lines.append("")
    lines.append(f"BORDERLINE ({len(border)}) — produce-adjacent but "
                 "OUTSIDE the keep sets (default LEAVE — your "
                 "ruling):")
    for e in border:
        note = _mark(e)
        lines.append(f"  row {e['row']:>3}  {e['code']:<4} "
                     f"{e['name'][:44]:<44} [{e['sub_category']}]"
                     + (f"  ← {note}" if note else ""))
    lines.append("")
    lines.append(f"LEAVE ({len(left)}) — archived to {ARCHIVE_TAB} "
                 "and deleted from master:")
    lines.append("  " + "; ".join(e["name"] for e in left))
    lines.append("")
    lines.append(f"Totals: keep {len(kept)} / borderline "
                 f"{len(border)} / leave {len(left)} — "
                 f"sub-category domain sets: {len(keep_sets)} labels")
    return "\n".join(lines)


def _fmt_g2() -> str:
    rows = [
        ("A", "Product_Name", "A", "kept"),
        ("B", "Category", "B", "kept"),
        ("C", "Size", "C", "kept"),
        ("D", "Woolworths_Price", "D", "kept"),
        ("E", "Coles_Price", "—", "DROPPED"),
        ("F", "Aldi_Price", "—", "DROPPED"),
        ("G", "Brand_Type", "E", "moved"),
        ("H", "Last_Updated", "F", "moved"),
        ("I", "Search_Keyword_Woolworths", "G", "moved"),
        ("J", "Search_Keyword_Coles", "—", "DROPPED"),
        ("K", "Search_Keyword_Aldi", "—", "DROPPED"),
        ("L", "Aldi Refresh", "—", "DROPPED"),
        ("M", "Woolworths_Specials", "H", "moved"),
        ("N", "Coles_Specials", "—", "DROPPED"),
        ("O", "Rewards_Points", "I", "moved"),
        ("P", "Keywords", "J", "moved"),
        ("Q", "Sub_Category", "K", "moved"),
        ("R", "Item_Code", "L", "moved"),
        ("S", "Preferred", "M", "moved"),
    ]
    lines = ["G2 — column drop (deletes run right-to-left: "
             "N, L, K, J, F, E):",
             "  old → new   header"]
    for old, name, new, fate in rows:
        marker = "  ✗" if fate == "DROPPED" else "  →"
        lines.append(f"  {marker} {old:<2} {new:<3} {name}")
    lines.append("  post-drop header == spec §3.1 (asserted verbatim "
                 "before any further step)")
    return "\n".join(lines)


def _fmt_g3(plan: dict, master13: list) -> str:
    from tools.parity_audit import is_ld_item_row

    lines: list = []
    renames = plan["renames"]
    lines.append(f"G3 — halal renames ({len(renames)} BUTCHERY rows; "
                 "FRUITS/OTHER untouched):")
    for idx, old, new in renames[:8]:
        lines.append(f"  LD row {idx + 1:>3}: {old[:40]} → {new[:44]}")
    if len(renames) > 8:
        lines.append(f"  … +{len(renames) - 8} more")

    planned = plan["planned"]
    lines.append("")
    lines.append(f"G3 — new blank master rows + codes "
                 f"({len(planned)} unpaired Local_Deals items):")
    for p in planned[:8]:
        lines.append(f"  {p['code']:<4} {p['name'][:44]:<44} "
                     f"[{p['subcategory']}]")
    if len(planned) > 8:
        lines.append(f"  … +{len(planned) - 8} more")
    matched = sum(1 for _c, kind in plan["code_map"].values()
                  if kind == "matched")
    lines.append(f"  matched to existing master rows: {matched} "
                 "(carry their existing code)")

    lines.append("")
    lines.append("G3 — Local_Deals col K: append header 'Item_Code' "
                 f"+ backfill {len(plan['code_map'])} item row(s); "
                 "blank Wool-only mirrors carry their master code")

    mf = plan["master_final"]
    lf = plan["ld_final"]
    ld_items = [(i, r) for i, r in enumerate(lf)
                if is_ld_item_row(i, r)]
    lines.append("")
    lines.append(f"G3 — final aligned order: master {len(mf) - 1} "
                 f"data rows / LD {len(ld_items)} item rows; "
                 f"first/last 5 pairs:")
    pairs = list(zip(mf[1:], [r for _i, r in ld_items]))
    head = pairs[:5]
    tail = pairs[-5:] if len(pairs) > 5 else []
    for m, l in head:
        lines.append(f"  {(_cell(m, 0) or '—')[:36]:<36} "
                     f"{_cell(m, 11):<4} <-> LD row "
                     f"{next(i for i, r in ld_items if r is l) + 1:>3} "
                     f"{(_cell(l, 0) or '—')[:32]:<32} "
                     f"{_cell(l, 10):<4}")
    if tail:
        lines.append("  …")
        for m, l in tail:
            lines.append(
                f"  {(_cell(m, 0) or '—')[:36]:<36} "
                f"{_cell(m, 11):<4} <-> LD row "
                f"{next(i for i, r in ld_items if r is l) + 1:>3} "
                f"{(_cell(l, 0) or '—')[:32]:<32} "
                f"{_cell(l, 10):<4}")
    return "\n".join(lines)


def preview(force_keep=(), force_leave=(), gate: str = "") -> int:
    """Read-only print of the G1/G2/G3 previews off the live sheet."""
    from tools.parity_audit import audit, format_report

    spreadsheet = _connect()
    master = _read_master(spreadsheet)
    ld = _read_ld(spreadsheet)
    width = max((len(r) for r in master), default=0)
    print(f"=== live probe: master {len(master)} rows x {width} "
          f"cols · Local_Deals {len(ld)} rows ===")

    if width >= 19 and (not gate or gate == "g1"):
        ruling = stay_leave(master)
        print()
        print(_fmt_g1(ruling, force_keep, force_leave))
    elif not gate or gate == "g1":
        print("\n[G1] master is already past G1 "
              f"({width} cols) — stay/leave not applicable")

    master13 = master
    if width >= 19:
        master13 = drop_columns(master)
        if not gate or gate == "g2":
            print()
            print(_fmt_g2())
    if len(master13[0] if master13 else []) == 13:
        plan = build_parity_plan(master13, ld)
        if not gate or gate == "g3":
            print()
            print(_fmt_g3(plan, master13))
        print()
        result = audit(plan["master_final"], plan["ld_final"])
        print(f"[audit on the PLANNED end-state] "
              f"{format_report(result)}")
    return 0


def audit_cmd() -> int:
    """Live parity audit — prints ALIGNED (exit 0) or the drift."""
    from tools.parity_audit import audit, format_report

    spreadsheet = _connect()
    result = audit(_read_master(spreadsheet), _read_ld(spreadsheet))
    print(format_report(result))
    return 0 if result["status"] == "aligned" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-shot v2 sheet migration (Round 2)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preview", help="G1/G2/G3 previews (read-only)")
    p.add_argument("--gate", choices=["g1", "g2", "g3"], default="")
    p.add_argument("--force-keep", default="",
                   help="comma-separated Item_Codes moved INTO keep")
    p.add_argument("--force-leave", default="",
                   help="comma-separated Item_Codes moved OUT OF keep")
    p.set_defaults(func=lambda a: preview(
        force_keep=a.force_keep.split(",") if a.force_keep else [],
        force_leave=a.force_leave.split(",") if a.force_leave else [],
        gate=a.gate))

    p = sub.add_parser("apply-stay-leave",
                       help="G1: Archive tab + retire LEAVE rows")
    p.add_argument("--force-keep", default="")
    p.add_argument("--force-leave", default="")
    p.set_defaults(func=lambda a: apply_stay_leave(
        force_keep=a.force_keep.split(",") if a.force_keep else [],
        force_leave=a.force_leave.split(",") if a.force_leave else []))

    sub.add_parser("apply-columns",
                   help="G2: drop E,F,J,K,L,N").set_defaults(
        func=lambda a: apply_columns())

    sub.add_parser("apply-parity",
                   help="G3: renames + blank rows + col K + "
                        "alignment").set_defaults(
        func=lambda a: apply_parity())

    sub.add_parser("audit",
                   help="parity audit (ALIGNED / drift)").set_defaults(
        func=lambda a: audit_cmd())

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
