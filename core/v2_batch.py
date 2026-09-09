"""v2 batch corrections (spec §4/§7): ONE call, every verdict, one
per-code reply. No pre-investigation — with one sheet and one list
there is nothing to investigate."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from core.local_deals import SECTION_ORDER, _numeric_price
from core.v2_read import IGNORED_PATH, TAB_NAME, VALIDITY_LABEL

MASTER_TAB = "Products_Master"
MASTER_CODE_IDX = 11          # 13-col layout: col L
LD_CODE_IDX = 10              # 11-col layout: col K
MASTER_COLS = 13              # A..M
LD_COLS = 11                  # A..K

DELETED_ROWS_PATH = (Path(__file__).resolve().parent.parent / "data"
                     / "deleted_rows.json")
REMOVE_SOURCE = "v2-batch-remove"

VERBS = ("done", "gone", "rename", "remove", "ignore")


def parse_verdicts(text: str) -> list:
    """'ABC done; DEF gone; GHI rename halal lamb shoulder; JKL
    remove; MNO ignore' -> [{'code','verb','arg'}].

    rename's arg = free text to the ';' / end. Unknown verbs ->
    {'code','verb':'?'} (rename without a new name counts as
    unknown — there is nothing to rename to). Empty tokens
    (stray ';') are skipped.
    """
    out: list = []
    for token in str(text or "").split(";"):
        parts = token.split(None, 2)
        if not parts:
            continue
        code = parts[0].strip().upper()
        verb = parts[1].strip().lower() if len(parts) > 1 else ""
        arg = parts[2].strip() if len(parts) > 2 else ""
        if verb not in VERBS or (verb == "rename" and not arg):
            out.append({"code": code, "verb": "?"})
            continue
        out.append({"code": code, "verb": verb, "arg": arg})
    return out


def _cell(row: list, idx: int) -> str:
    return str(row[idx]).strip() if row and len(row) > idx else ""


def _is_ld_item_row(index: int, row: list) -> bool:
    """LD ITEM rows only (header / validity / section rows exempt) —
    the same exemption tools/parity_audit applies."""
    if index == 0:
        return False
    first = _cell(row, 0)
    if first in SECTION_ORDER or first == VALIDITY_LABEL:
        return False
    return bool(first or _cell(row, LD_CODE_IDX))


def _shift(indices: dict, deleted: int) -> None:
    """Decrement every stored index above a just-deleted row."""
    for key in indices:
        if indices[key] > deleted:
            indices[key] -= 1


def _master_ordinal(master_grid: list, idx: int) -> int:
    """0-based ITEM ordinal of master grid row ``idx`` (the k-th
    NAMED data row) — parity pairs it with the k-th LD item row
    (tools/parity_audit semantics; the LD side's structural rows make
    raw grid indices non-comparable)."""
    return sum(1 for r in master_grid[1:idx] if _cell(r, 0))


def _ld_ordinal(ld_grid: list, idx: int) -> int:
    """0-based ITEM ordinal of LD grid row ``idx`` (the k-th item
    row, structural rows exempt)."""
    return sum(1 for i in range(1, idx) if _is_ld_item_row(i,
                                                           ld_grid[i]))


def _archive_pair(archive_path: Path, code: str, master_row: list,
                  ld_row: list, master_sheet_row: int,
                  ld_sheet_row: int) -> None:
    """ARCHIVE FIRST: both rows into deleted_rows.json BEFORE any
    delete (existing schema, additive side/code keys)."""
    archive: list = []
    try:
        loaded = json.loads(
            archive_path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            archive = loaded
    except (OSError, ValueError):
        archive = []
    stamp = datetime.now().isoformat(timespec="seconds")
    archive.append({"deleted_at": stamp, "source": REMOVE_SOURCE,
                    "side": "master", "code": code,
                    "row_index": master_sheet_row,
                    "row": [str(c) for c in master_row]})
    archive.append({"deleted_at": stamp, "source": REMOVE_SOURCE,
                    "side": "local_deals", "code": code,
                    "row_index": ld_sheet_row,
                    "row": [str(c) for c in ld_row]})
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(
        json.dumps(archive, indent=2, ensure_ascii=False),
        encoding="utf-8")


def apply_verdicts(verdicts: list, *, master_ws=None, ld_ws=None,
                   archive_path=None, ignored_path=None,
                   audit_fn=None) -> list:
    """ONE read of both tabs, then per verdict (spec §4 semantics):

    done   -> VERIFY-ONLY (Q14): master D real price AND keyword G
              present -> '[CODE] ✓ done — off the list'; else names
              exactly what is still blank. WRITES NOTHING.
    gone   -> master D = 'GONE' (Q13). Row kept everywhere.
    rename -> master A = new name AND LD A = new name when the LD row
              is named (Q15). Codes/prices untouched.
    remove -> ARCHIVE FIRST, then delete the SAME row index on both
              tabs (parity preserved, Q16).
    ignore -> append '[CODE] name' to the ignore file (hidden per
              spec §6).

    Unknown code -> '[CODE] ✗ unknown code' — remaining verdicts
    still execute. One clear+update per tab max; the parity audit
    after MUST be ALIGNED (else RuntimeError — no partial silent
    state). Returns the per-code reply lines in verdict order.
    """
    from core.v2_read import MASTER_TAB

    if master_ws is None or ld_ws is None:
        from core.sheets_client import connect_spreadsheet
        spreadsheet = connect_spreadsheet()
        master_ws = master_ws or spreadsheet.worksheet(MASTER_TAB)
        ld_ws = ld_ws or spreadsheet.worksheet(TAB_NAME)

    archive_path = Path(archive_path) if archive_path \
        else DELETED_ROWS_PATH
    ignored_path = Path(ignored_path) if ignored_path else IGNORED_PATH
    if audit_fn is None:
        from tools.parity_audit import audit as audit_fn

    master_grid = [list(r) for r in
                   (master_ws.get_all_values() or [])]
    ld_grid = [list(r) for r in (ld_ws.get_all_values() or [])]

    master_by_code = {_cell(r, MASTER_CODE_IDX).upper(): i
                      for i, r in enumerate(master_grid[1:], 1)
                      if _cell(r, MASTER_CODE_IDX)}
    ld_by_code = {_cell(r, LD_CODE_IDX).upper(): i
                  for i, r in enumerate(ld_grid)
                  if _is_ld_item_row(i, r)
                  and _cell(r, LD_CODE_IDX)}

    replies: list = []
    master_changed = ld_changed = False
    for v in verdicts:
        code, verb = str(v.get("code", "")).upper(), v.get("verb")
        m_idx = master_by_code.get(code)
        if verb == "?":
            replies.append(f"[{code}] ✗ unknown verdict")
            continue
        if m_idx is None:
            replies.append(f"[{code}] ✗ unknown code")
            continue
        m_row = master_grid[m_idx]

        if verb == "done":
            price = _numeric_price(_cell(m_row, 3))
            keyword = _cell(m_row, 6)
            if price is not None and keyword:
                replies.append(f"[{code}] ✓ done — off the list")
            else:
                blank = []
                if price is None:
                    blank.append("Woolworths price (col D)")
                if not keyword:
                    blank.append("search keyword (col G)")
                replies.append(f"[{code}] ✗ not done — still blank: "
                               f"{' and '.join(blank)}")

        elif verb == "gone":
            m_row[3] = "GONE"
            master_changed = True
            replies.append(f"[{code}] ✓ marked GONE at Woolworths "
                           f"(row kept)")

        elif verb == "rename":
            new_name = str(v.get("arg", "")).strip()
            m_row[0] = new_name
            master_changed = True
            note = ""
            l_idx = ld_by_code.get(code)
            if l_idx is not None and _cell(ld_grid[l_idx], 0):
                ld_grid[l_idx][0] = new_name
                ld_changed = True
            else:
                note = " (LD row unnamed — master side only)"
            replies.append(f"[{code}] ✓ renamed to “{new_name}”"
                           f"{note}")

        elif verb == "remove":
            l_idx = ld_by_code.get(code)
            if l_idx is None or _ld_ordinal(ld_grid, l_idx) != \
                    _master_ordinal(master_grid, m_idx):
                raise RuntimeError(
                    f"[{code}] parity drift: the LD pairing for the "
                    f"remove verdict is not the paired item row — "
                    f"run tools/migrate_v2.py audit and fix the "
                    f"sheet first (nothing written)")
            _archive_pair(archive_path, code, m_row,
                          ld_grid[l_idx], m_idx + 1, l_idx + 1)
            del master_grid[m_idx]
            del ld_grid[l_idx]
            _shift(master_by_code, m_idx)
            _shift(ld_by_code, l_idx)
            master_changed = ld_changed = True
            replies.append(f"[{code}] ✓ removed (archived to "
                           f"deleted_rows.json; both tabs)")

        elif verb == "ignore":
            name = _cell(m_row, 0)
            ignored_path.parent.mkdir(parents=True, exist_ok=True)
            with ignored_path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{code}] {name}\n")
            replies.append(f"[{code}] ✓ ignored — hidden from the "
                           f"missing list (reveal: ignored)")

    if master_changed:
        master_ws.clear()
        master_ws.update(values=master_grid,
                         range_name=f"A1:M{len(master_grid)}")
    if ld_changed:
        ld_ws.clear()
        ld_ws.freeze(rows=2)
        ld_ws.update(values=ld_grid,
                     range_name=f"A1:K{len(ld_grid)}")

    result = audit_fn(master_grid, ld_grid)
    if result.get("status") != "aligned":
        from tools.parity_audit import format_report
        raise RuntimeError("post-batch parity audit FAILED — "
                           + format_report(result))
    return replies
