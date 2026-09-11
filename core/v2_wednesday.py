"""Wednesday v2 (spec §10): parse the two pasted Woolworths docx files,
sync prices/markers/deal-rates to the 13-col master, run the A2 parity
step, post specials (topic 206) + the ONE list (topic 208). No pause,
no scp, no queues. ≤30s.

Parse chain is ENTIRELY the kept Round-3 modules (zero reinvention):
extractors.doc_parser (main docx) + extractors.specials_parser
(classify_special per specials item) + core.multibuy (deal rates) +
tools.parity_audit (A2 outcomes) + core.item_codes (mirror codes) +
core.v2_read (the ONE list) + core.local_deals._send_message (posts).
"""
from __future__ import annotations

import os
import time
from datetime import date

MASTER_TAB = "Products_Master"
MASTER_CODE_IDX = 11          # 13-col layout: col L
LD_CODE_IDX = 10              # 11-col layout: col K
PRICE_IDX = 3                 # col D — Woolworths_Price
KEYWORD_IDX = 6               # col G — the sync keyword
SPECIALS_IDX = 7              # col H — Woolworths_Specials
MASTER_COLS = 13              # A..M
LD_COLS = 11                  # A..K

SPECIALS_TOPIC_ID = 206       # env override TELEGRAM_SPECIALS_TOPIC_ID
LISTS_TOPIC_ID = 208          # env override TELEGRAM_LISTS_TOPIC_ID

GONE_MARKER = "GONE"

# Local_Deals layout (user directive 2026-09-12): the LD tab mirrors
# Products_Master ROW-FOR-ROW — a header row + item rows only. These
# structural labels are legacy furniture; the parity step strips them
# on sight and never writes them back.
LD_STRUCTURAL_LABELS = ("Prices valid until", "BUTCHERY", "FRUITS",
                        "OTHER")


def _norm(text) -> str:
    """Case-insensitive, whitespace-collapsed match key."""
    return " ".join(str(text or "").split()).lower()


def _cell(row: list, idx: int) -> str:
    return str(row[idx]).strip() if row and len(row) > idx else ""


def _topics() -> tuple[int, int]:
    """(specials_topic, lists_topic) with .env override per target."""
    try:
        specials = int(os.getenv("TELEGRAM_SPECIALS_TOPIC_ID", "")
                       or SPECIALS_TOPIC_ID)
    except ValueError:
        specials = SPECIALS_TOPIC_ID
    try:
        lists = int(os.getenv("TELEGRAM_LISTS_TOPIC_ID", "")
                    or LISTS_TOPIC_ID)
    except ValueError:
        lists = LISTS_TOPIC_ID
    return specials, lists


def parse_inputs() -> tuple[list, list]:
    """(main_items, specials_items) — main via
    extractors.doc_parser.parse_docx_cache('woolworths') (the same
    entry the existing doc_parser flow uses); specials via
    parse_docx on Woolworths_Specials.docx + per-item
    classify_special (specials_parser has no doc-level entry, so
    this is the plan's sanctioned fallback — detect_special's
    SAVE/FOR logic already runs inside parse_docx's marker
    detection). Missing files -> empty lists (the report shows it).
    """
    from pathlib import Path

    from extractors.doc_parser import parse_docx_cache
    from extractors.specials_parser import parse_specials_docx

    main_items = parse_docx_cache("woolworths")

    specials_items: list = []
    tracker_dir = Path(__file__).resolve().parent.parent
    specials_path = tracker_dir / "Woolworths_Specials.docx"
    if not specials_path.is_file():
        specials_path = Path.cwd() / "Woolworths_Specials.docx"
    if specials_path.is_file():
        try:
            specials_items = parse_specials_docx(str(specials_path),
                                                 store="woolworths")
        except FileNotFoundError:
            specials_items = []
    return main_items, specials_items


def match_index(master_grid: list[list]) -> dict:
    """normalized keyword (col G idx 6) -> row index (0-based grid
    index). Case-insensitive, whitespace-collapsed. Rows with a
    blank keyword are NOT indexed; the header row is skipped."""
    index: dict = {}
    for i, row in enumerate(master_grid):
        if i == 0:
            continue
        kw = _norm(_cell(row, KEYWORD_IDX))
        if kw:
            index[kw] = i
    return index


def plan_sync(master_grid: list[list], main_items: list,
              specials_items: list, today: date,
              specials_only: bool = False) -> dict:
    """Pure grid-in plan-out (offline-testable). Returns
    {'writes': [(idx, col, value)], 'matched': int, 'na': [names],
    'unavailable': [names], 'multibuy': [names], 'cleared_h': [names],
    'unmatched': [names]}.

    Semantics (spec §10 + §17.6 + §4.3):
    - main-docx item whose keyword matches -> D = price (2-dp); a real
      price OVERWRITES GONE / N/A / unavailable markers.
    - keyword row ABSENT from the main docx -> D = 'N/A <today>' —
      UNLESS its current D is 'GONE' (GONE survives until a real
      price returns; never N/A'd).
    - present but no usable price -> D = 'unavailable <today>'.
    - specials-docx match with multibuy terms (qty/total parsed from
      special_desc, e.g. '2 for $6'; rate via core.multibuy
      effective_unit_rate) -> D = per-unit rate,
      H = 'multi-buy N/$X'.
    - specials match without multibuy -> H = special_desc.
    - keyword row whose H carried terms but is ABSENT from the new
      specials docx -> H cleared (deal ended; D already holds the
      main-docx normal price).
    - docx line with NO keyword match -> 'unmatched' report only —
      NEVER a write (no auto-add, §4.2).

    specials_only=True (user rule 2026-09-10, for weeks between main
    list cleanups): pass 1 (main-docx D writes, unavailable markers,
    N/A sweep, main-docx unmatched) is SKIPPED entirely — manual D
    prices survive; only the specials docx acts (H terms, deal rates,
    deal-end clears).
    """
    from core.multibuy import (effective_unit_rate, encode_multibuy_cell,
                               parse_multibuy)
    from extractors.specials_parser import classify_special

    kw_index = match_index(master_grid)
    writes: dict = {}          # (idx, col) -> value; specials pass
    matched = 0                # real-price writes from the main docx
    na: list = []
    unavailable: list = []
    multibuy: list = []
    cleared_h: list = []
    unmatched: list = []

    def _note_unmatched(name: str) -> None:
        if name and name not in unmatched:
            unmatched.append(name)

    # --- pass 1: the main docx -> D prices / markers -------------
    # (skipped entirely in specials_only mode)
    matched_main: dict = {}    # grid idx -> item
    for item in ([] if specials_only else main_items):
        idx = kw_index.get(_norm(getattr(item, "raw_name", "")))
        if idx is None:
            _note_unmatched(getattr(item, "raw_name", ""))
            continue
        matched_main[idx] = item

    for idx, item in matched_main.items():
        name = _cell(master_grid[idx], 0)
        price = getattr(item, "price", None)
        if price is not None and price > 0:
            writes[(idx, PRICE_IDX)] = f"${float(price):.2f}"
            matched += 1
        else:
            writes[(idx, PRICE_IDX)] = f"unavailable {today.isoformat()}"
            unavailable.append(name)

    for idx in kw_index.values():
        if specials_only or idx in matched_main:
            continue
        row = master_grid[idx]
        if _cell(row, PRICE_IDX).upper() == GONE_MARKER:
            continue           # GONE survives until a price returns
        writes[(idx, PRICE_IDX)] = f"N/A {today.isoformat()}"
        na.append(_cell(row, 0))

    # --- pass 2: the specials docx -> H terms + D deal rates -----
    matched_specials: dict = {}   # grid idx -> (item, class)
    for item in specials_items:
        idx = kw_index.get(_norm(getattr(item, "raw_name", "")))
        if idx is None:
            _note_unmatched(getattr(item, "raw_name", ""))
            continue
        cls = classify_special(bool(getattr(item, "is_special", False)),
                               getattr(item, "special_desc", "") or "")
        matched_specials[idx] = (item, cls)

    for idx, (item, cls) in matched_specials.items():
        name = _cell(master_grid[idx], 0)
        desc = getattr(item, "special_desc", "") or ""
        terms = parse_multibuy(desc) if cls == "multi-buy" else None
        if terms:
            qty, total = terms
            rate = effective_unit_rate(qty, total)
            writes[(idx, PRICE_IDX)] = f"${rate:.2f}"
            writes[(idx, SPECIALS_IDX)] = encode_multibuy_cell(qty, total)
            multibuy.append(name)
        else:
            writes[(idx, SPECIALS_IDX)] = desc

    # --- deal-end sweep: H terms whose deal left the docx ---------
    for idx in kw_index.values():
        if idx in matched_specials:
            continue
        if _cell(master_grid[idx], SPECIALS_IDX):
            writes[(idx, SPECIALS_IDX)] = ""
            cleared_h.append(_cell(master_grid[idx], 0))

    # No-op writes (cell already holds the value) stay out of the plan.
    final: list = []
    for (idx, col), value in writes.items():
        if _cell(master_grid[idx], col) != value:
            final.append((idx, col, value))
    return {"writes": final, "matched": matched, "na": na,
            "unavailable": unavailable, "multibuy": multibuy,
            "cleared_h": cleared_h, "unmatched": unmatched}


def apply_writes(master_ws, master_grid: list[list],
                 writes: list) -> None:
    """One clear+update (A1:M) when writes exist; no-op otherwise.
    Applies the writes onto the grid first, then writes the whole
    grid (the v2_batch write pattern)."""
    if not writes:
        return
    for idx, col, value in writes:
        row = master_grid[idx]
        while len(row) <= col:
            row.append("")
        row[col] = value
    master_ws.clear()
    master_ws.update(values=master_grid,
                     range_name=f"A1:M{len(master_grid)}")


def _heal_ld_layout(ld_grid: list[list],
                    master_grid: list[list]) -> list[str]:
    """Heal Local_Deals layout drift BEFORE the audit (user directive
    2026-09-12: LD mirrors the master tab row-for-row).

    - A coded row with a BLANK Col A name is a Wool-only mirrored
      row whose name was lost (legacy mirrors) — it is re-named from
      the master row sharing its Item_Code (word-for-word).
    - A structural furniture row (stamp / section title) is dropped.

    Mutates ld_grid in place. Returns report lines ([] when clean).
    """
    lines: list[str] = []
    code_to_name: dict[str, str] = {}
    for row in master_grid[1:]:
        name = _cell(row, 0)
        code = _cell(row, MASTER_CODE_IDX).upper()
        if name and code:
            code_to_name.setdefault(code, name)

    healed: list[list] = []
    for i, row in enumerate(ld_grid):
        if i == 0:                       # header row stays
            healed.append(row)
            continue
        first = _cell(row, 0)
        if first in LD_STRUCTURAL_LABELS:
            lines.append(f"  healed: LD row {i + 1} structural row "
                         f"'{first}' removed")
            continue
        code = _cell(row, LD_CODE_IDX).upper()
        if not first and code:
            name = code_to_name.get(code)
            if name:
                row = list(row)
                row[0] = name
                lines.append(f"  healed: LD row {i + 1} named "
                             f"'{name}' [{code}] (was blank)")
        healed.append(row)
    ld_grid[:] = healed
    return lines


def _move_inserted_row(master_grid: list[list],
                       ld_grid: list[list],
                       miss: dict) -> tuple[bool, bool, list[str]]:
    """Attempt ONE deterministic middle-insert repair (user directive
    2026-09-12: 'anything not in order to be fixed by' the sync).

    The audit break names the first code-pair mismatch. The side whose
    NEXT row carries the other side's break code is the side holding
    the inserted row — that row is moved to that tab's bottom (the
    layout's append convention), realigning every later pair.

    Returns (master_moved, ld_moved, report_lines) — all False/[]
    when the break is not a single-row insert (deletion/reorder):
    the caller then aborts with the verbatim alert.
    """
    m_sheet = int(miss.get("master_sheet_row") or 0)
    l_sheet = int(miss.get("ld_sheet_row") or 0)
    m_code = str(miss.get("master_code") or "").strip().upper()
    l_code = str(miss.get("ld_code") or "").strip().upper()
    if not (m_sheet and l_sheet):
        return False, False, []

    def _code(grid: list, idx: int) -> str:
        row = grid[idx] if 0 <= idx < len(grid) else []
        return _cell(row, MASTER_CODE_IDX if grid is master_grid
                     else LD_CODE_IDX).upper()

    # Master-side insert: LD's break row pairs with master's NEXT row.
    if l_code and _code(master_grid, m_sheet) == l_code:
        row = master_grid.pop(m_sheet - 1)
        master_grid.append(row)
        return True, False, [
            f"  healed: master row {m_sheet} "
            f"('{_cell(row, 0) or m_code}') moved to the bottom "
            f"(mid-tab insert)"]
    # LD-side insert: master's break row pairs with LD's NEXT row.
    if m_code and _code(ld_grid, l_sheet) == m_code:
        row = ld_grid.pop(l_sheet - 1)
        ld_grid.append(row)
        return False, True, [
            f"  healed: LD row {l_sheet} "
            f"('{_cell(row, 0) or m_code}') moved to the bottom "
            f"(mid-tab insert)"]
    return False, False, []


def parity_step(master_grid: list[list], ld_grid: list[list],
                ld_ws, master_ws=None) -> str:
    """tools/parity_audit.audit on the two grids (§18/A2):
    ALIGNED -> one clean line, continue. bottom_append -> AUTO-MIRROR
    during the run (blank counterpart rows appended, codes reserved
    via core.item_codes, report lines, continue). middle_insert ->
    one deterministic repair attempt (_move_inserted_row); when the
    break is not a single-row insert, print the VERBATIM A2 alert and
    return 'ABORT' (run exits 1: no writes, no posts).

    Before the audit, legacy LD layout drift is healed in place
    (_heal_ld_layout): structural rows dropped, coded blank rows
    named from their master pair — the layout the user pinned
    2026-09-12 (row # = row #, no blank lines)."""
    heal_lines = _heal_ld_layout(ld_grid, master_grid)
    if heal_lines:
        ld_ws.clear()
        ld_ws.freeze(rows=1)
        ld_ws.update(values=ld_grid,
                     range_name=f"A1:K{len(ld_grid)}")

    from tools.parity_audit import audit, format_report

    master_changed = ld_changed = False
    result = audit(master_grid, ld_grid)
    if result["status"] == "aligned":
        report = format_report(result)
        return "\n".join(heal_lines + [report]) if heal_lines \
            else report
    if result["status"] == "middle_insert":
        moved_m, moved_l, fix_lines = _move_inserted_row(
            master_grid, ld_grid, result["misses"][0])
        master_changed, ld_changed = moved_m, moved_l
        heal_lines.extend(fix_lines)
        if moved_m or moved_l:
            result = audit(master_grid, ld_grid)
    if result["status"] == "middle_insert":
        print(result["alert"])     # VERBATIM (§18/A2.2) — never edit
        return "ABORT"

    # bottom_append -> AUTO-MIRROR (§18/A2.1)
    from core import item_codes

    lines = [format_report(result)]
    sheet_id = item_codes._spreadsheet_id(ld_ws)
    taken = item_codes.retired_codes(item_codes.load_registry())
    for row in master_grid[1:]:
        code = _cell(row, MASTER_CODE_IDX).upper()
        if code:
            taken.add(code)
    for row in ld_grid:
        code = _cell(row, LD_CODE_IDX).upper()
        if code:
            taken.add(code)

    def _reserve(seed: str) -> str:
        code = item_codes.generate_codes(taken, 1, seed=seed)[0]
        taken.add(code)
        return code

    pending: list[tuple[str, int]] = []   # (code, 1-based sheet row)

    for m in result["misses"]:
        if m["side"] == "master":
            # user added master row(s) at the end -> blank LD mirror
            row = master_grid[m["sheet_row"] - 1]
            name = _cell(row, 0)
            code = _cell(row, MASTER_CODE_IDX).upper()
            if not code:
                code = _reserve(f"wednesday-mirror:master:"
                                f"{m['sheet_row']}:{name}")
                # the code is the PAIR KEY — it must live on BOTH
                # sides or the next audit reads a code break.
                while len(row) <= MASTER_CODE_IDX:
                    row.append("")
                row[MASTER_CODE_IDX] = code
                master_changed = True
            ld_grid.append([name] + [""] * (LD_COLS - 2) + [code])
            pending.append((code, len(ld_grid)))
            ld_changed = True
            lines.append(f"  mirrored -> LD row {len(ld_grid)}: "
                         f"{name} [{code}]")
        elif m["side"] == "ld":
            # extra LD item row(s) -> blank master mirror
            row = ld_grid[m["sheet_row"] - 1]
            name = _cell(row, 0)
            code = _cell(row, LD_CODE_IDX).upper()
            if not code:
                code = _reserve(f"wednesday-mirror:ld:"
                                f"{m['sheet_row']}:{name}")
                while len(row) <= LD_CODE_IDX:
                    row.append("")
                row[LD_CODE_IDX] = code
                ld_changed = True
            master_row = [""] * MASTER_COLS
            master_row[0] = name
            master_row[MASTER_CODE_IDX] = code
            master_grid.append(master_row)
            pending.append((code, len(master_grid)))
            master_changed = True
            lines.append(f"  mirrored -> master row "
                         f"{len(master_grid)}: {name} [{code}]")

    if master_changed and master_ws is not None:
        master_ws.clear()
        master_ws.update(values=master_grid,
                         range_name=f"A1:M{len(master_grid)}")
    if ld_changed:
        ld_ws.clear()
        ld_ws.freeze(rows=1)
        ld_ws.update(values=ld_grid, range_name=f"A1:K{len(ld_grid)}")
    # Confirm AFTER the write succeeded (item_codes discipline D-IC4).
    for code, row_index in pending:
        item_codes.confirm_code(code, row_index,
                                spreadsheet_id=sheet_id)
    if heal_lines:
        return "\n".join(heal_lines + [""] + lines)
    return "\n".join(lines)


def render_docx_specials_section(items: list) -> str:
    """The PASTED specials list as a Telegram section — DEALS ONLY
    (2026-09-10 user rule: never show plain items; both deal types
    get their own animated group). Grouping uses the D25 vocabulary
    (classify_special): multi-buy / discount; everything else is
    skipped. Multi-buy entries also show the per-unit rate."""
    from core.multibuy import effective_unit_rate, parse_multibuy
    from extractors.specials_parser import classify_special
    from core.sydney_time import sydney_today

    multibuy: list = []
    discounted: list = []
    for item in items:
        desc = (getattr(item, "special_desc", "") or "").strip()
        cls = classify_special(bool(desc), desc)
        if cls == "multi-buy":
            multibuy.append(item)
        elif cls == "discount":
            discounted.append(item)
    total = len(multibuy) + len(discounted)
    if not total:
        return ""

    def _entry(n: int, item) -> list:
        price = getattr(item, "price", None)
        desc = (getattr(item, "special_desc", "") or "").strip()
        if price:
            detail = f"   💵 ${price:.2f}"
        else:
            detail = "   🚫 out of stock"
        if desc:
            terms = parse_multibuy(desc)
            if terms:
                qty, bundle = terms
                detail += (f" · 🎁 {desc} "
                           f"(= ${effective_unit_rate(qty, bundle):.2f} each)")
            else:
                detail += f" · ✂️ {desc}"
        return [f"  {n}. {item.raw_name}", detail]

    lines = [f"🏷️ WOOLWORTHS SPECIALS — {total} DEALS 🛒"]
    if multibuy:
        lines += ["", "📦 MULTI-BUY — buy in bulk & save",
                  "─" * 28]
        for n, item in enumerate(multibuy, 1):
            lines.extend(_entry(n, item))
    if discounted:
        lines += ["", "💰 DISCOUNTED", "─" * 28]
        for n, item in enumerate(discounted, 1):
            lines.extend(_entry(n, item))
    lines += ["", f"📊 {total} deals found in your specials list"
              f" · ⏱️ {sydney_today().isoformat()}"]
    return "\n".join(lines)


def render_specials_post(worksheet=None) -> str:
    """Specials Telegram post: specials_reporter data + style kit —
    ONE fresh master read of col H + D (post-write in live runs)."""
    from core.specials_reporter import (format_specials_report,
                                        get_active_specials)

    specials = get_active_specials(store="woolworths",
                                   worksheet=worksheet)
    return format_specials_report(specials, "woolworths")


def _receipt(tag: str, receipt: dict, thread) -> None:
    """The S32-style receipt line per post (grep target)."""
    if receipt.get("ok"):
        print(f"[telegram] ok message_id={receipt.get('message_id')} "
              f"chat={receipt.get('chat_id')} thread={thread}")
    else:
        print(f"[telegram] {tag} post NOT delivered "
              f"(failure line above)")


def run(dry_run: bool = False, send: bool = True,
        specials_only: bool = False) -> int:
    """Full pipeline: parse -> read both tabs -> parity_step ->
    plan_sync -> apply_writes (skipped in dry-run) -> TWO posts via
    core.local_deals._send_message (skipped in dry-run / send=False;
    list post = v2_read.read_tabs + missing_list + render_list).
    Prints the receipt line per post ('[telegram] ok message_id=…').
    Console always ends with: matched/unmatched/marker counts + the
    unmatched names + elapsed seconds. Returns 0, or 1 on the
    middle-insert abort (§18/A2.2).

    specials_only=True skips the main-docx pass (no D writes / no N/A
    sweep — manual prices survive); the specials docx alone updates
    H terms, deal rates and deal-end clears."""
    from core.local_deals import TAB_NAME, TELEGRAM_CHAT_ID, \
        _send_message
    from core.sheets_client import _load_env, connect_spreadsheet
    from core.specials_reporter import get_active_specials
    from core.sydney_time import sydney_today
    from core.telegram_format import split_message
    from core.v2_read import missing_list, read_tabs, render_list

    _load_env()
    started = time.time()
    main_items, specials_items = parse_inputs()

    spreadsheet = connect_spreadsheet()
    master_ws = spreadsheet.worksheet(MASTER_TAB)
    ld_ws = spreadsheet.worksheet(TAB_NAME)
    master_grid = [list(r) for r in
                   (master_ws.get_all_values() or [])]
    ld_grid = [list(r) for r in (ld_ws.get_all_values() or [])]

    report = parity_step(master_grid, ld_grid, ld_ws,
                         master_ws=master_ws)
    print(report)
    if report == "ABORT":
        return 1

    plan = plan_sync(master_grid, main_items, specials_items,
                     sydney_today(), specials_only=specials_only)
    if specials_only:
        print("[specials-only] main-docx pass SKIPPED — col D "
              "untouched (no N/A sweep; manual prices survive)")
    if not dry_run:
        apply_writes(master_ws, master_grid, plan["writes"])

    if send and not dry_run:
        bot_token = os.getenv("TELEGRAM_CLAW_BOT", "")
        specials_topic, lists_topic = _topics()
        # sheet-tracked specials first — but never a bare "No active
        # specials." above the pasted list's deals (user fix)
        docx_section = render_docx_specials_section(specials_items)
        sheet_deals = get_active_specials(store="woolworths",
                                          worksheet=master_ws)
        parts: list = []
        if sheet_deals:
            parts.append(render_specials_post(master_ws).rstrip())
        if docx_section:
            parts.append(docx_section)
        post = "\n\n".join(parts) if parts else "No active specials."
        # persist for the `specials` verb's "Latest Wednesday report"
        # view (fresh < 7 days)
        try:
            from pathlib import Path
            report_path = (Path(__file__).resolve().parent.parent
                           / "data" / "ww_specials_report.txt")
            report_path.write_text(
                f"# generated {sydney_today().isoformat()}\n{post}\n",
                encoding="utf-8")
        except OSError:
            pass  # report persistence is best-effort, never block
        for chunk in split_message(post):
            _receipt("specials",
                     _send_message(bot_token, TELEGRAM_CHAT_ID,
                                   chunk,
                                   thread_id=specials_topic),
                     specials_topic)
        master, ld = read_tabs()
        list_text = render_list(missing_list(master, ld))
        for chunk in split_message(list_text):
            _receipt("list", _send_message(bot_token, TELEGRAM_CHAT_ID,
                                           chunk,
                                           thread_id=lists_topic),
                     lists_topic)

    elapsed = time.time() - started
    print(f"[wednesday] matched={plan['matched']} "
          f"na={len(plan['na'])} "
          f"unavailable={len(plan['unavailable'])} "
          f"multibuy={len(plan['multibuy'])} "
          f"cleared_h={len(plan['cleared_h'])} "
          f"unmatched={len(plan['unmatched'])} "
          f"writes={len(plan['writes'])} elapsed={elapsed:.1f}s")
    for name in plan["unmatched"]:
        print(f"  unmatched: {name}")
    for name in plan["na"]:
        print(f"  n/a: {name}")
    for name in plan["unavailable"]:
        print(f"  unavailable: {name}")
    for name in plan["multibuy"]:
        print(f"  multi-buy: {name}")
    for name in plan["cleared_h"]:
        print(f"  deal ended: {name}")
    return 0
