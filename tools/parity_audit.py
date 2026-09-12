"""Parity audit (spec §18/A2 semantics; Round 4 wires it into Wednesday).

Pairs master data row N (Item_Code col L, 0-based idx 11) with the Nth
Local_Deals ITEM row (code col L, idx 11 — the Nazar column moved it
from K, 2026-09-12). LD structural rows — the header, the "Prices
valid until" stamp row, and the FRUITS/BUTCHERY/OTHER section-title
rows — are exempt (spec §3.3 offsets around them).

Three outcomes (A2):
  aligned        — silence (a single clean line at most)
  bottom_append  — extra row(s) at the END of either tab; reported
                   only this round (Round 4's Wednesday AUTO-MIRRORS)
  middle_insert  — a code break INSIDE the sequence; alert verbatim:
                   "row #N was inserted in the middle — move it to the
                   bottom manually and run sync again to copy it over
                   to the other sheet."

Pure grid-in/dict-out — offline testable; the caller owns sheet reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.local_deals import SECTION_ORDER  # noqa: E402

MASTER_CODE_IDX = 11        # 13-col layout: col L
LD_CODE_IDX = 11            # 12-col layout: col L (Nazar added 1)
VALIDITY_LABEL = "Prices valid until"

MIDDLE_INSERT_ALERT = (
    "row #{n} was inserted in the middle — move it to the bottom "
    "manually and run sync again to copy it over to the other sheet.")


def _cell(row: list, idx: int) -> str:
    return str(row[idx]).strip() if len(row) > idx else ""


def is_ld_item_row(index: int, row: list) -> bool:
    """True for Local_Deals ITEM rows (structural rows exempt).

    Exempt: the header (index 0), the validity stamp row, and the
    section-title rows. An item row has a Col A name or a col K code
    (Wool-only mirrored rows are Col-A-blank but coded).
    """
    if index == 0:
        return False
    first = _cell(row, 0)
    if first in SECTION_ORDER or first == VALIDITY_LABEL:
        return False
    return bool(first or _cell(row, LD_CODE_IDX))


def _row_dict(side: str, sheet_row: int, name: str, code: str) -> dict:
    return {"side": side, "sheet_row": sheet_row, "name": name,
            "code": code}


def audit(master_grid: list, ld_grid: list) -> dict:
    """Classify tab parity per A2. See module docstring.

    Returns:
        {'status': 'aligned' | 'bottom_append' | 'middle_insert',
         'misses': [row dicts], 'alert': str | None}.
    """
    master_rows = [(i + 2, r)                       # sheet row numbers
                   for i, r in enumerate(master_grid[1:])
                   if _cell(r, 0)]
    ld_items = [(i + 1, r)                          # sheet row numbers
                for i, r in enumerate(ld_grid)
                if is_ld_item_row(i, r)]

    n = min(len(master_rows), len(ld_items))
    break_at = None
    for k in range(n):
        m_code = _cell(master_rows[k][1], MASTER_CODE_IDX).upper()
        l_code = _cell(ld_items[k][1], LD_CODE_IDX).upper()
        if m_code != l_code:
            break_at = k
            break

    if break_at is not None:
        k = break_at
        m_sheet, m_row = master_rows[k]
        l_sheet, l_row = ld_items[k]
        misses = [{
            "side": "pair",
            "master_sheet_row": m_sheet,
            "ld_sheet_row": l_sheet,
            "master_name": _cell(m_row, 0),
            "master_code": _cell(m_row, MASTER_CODE_IDX),
            "ld_name": _cell(l_row, 0),
            "ld_code": _cell(l_row, LD_CODE_IDX),
        }]
        return {"status": "middle_insert", "misses": misses,
                "alert": MIDDLE_INSERT_ALERT.format(n=l_sheet)}

    misses: list[dict] = []
    for sheet_row, row in master_rows[n:]:
        misses.append(_row_dict("master", sheet_row, _cell(row, 0),
                                _cell(row, MASTER_CODE_IDX)))
    for sheet_row, row in ld_items[n:]:
        misses.append(_row_dict("ld", sheet_row, _cell(row, 0),
                                _cell(row, LD_CODE_IDX)))
    if misses:
        return {"status": "bottom_append", "misses": misses,
                "alert": None}
    return {"status": "aligned", "misses": [], "alert": None}


def format_report(result: dict) -> str:
    """Human-readable audit line(s); 'ALIGNED' when clean."""
    status = result.get("status")
    if status == "aligned":
        return "ALIGNED"
    lines = [status.upper()]
    for m in result.get("misses", []):
        if m.get("side") == "pair":
            lines.append(
                f"  master row {m['master_sheet_row']} "
                f"({m['master_name'] or '—'} / {m['master_code'] or '—'})"
                f" <-> LD row {m['ld_sheet_row']} "
                f"({m['ld_name'] or '—'} / {m['ld_code'] or '—'})")
        else:
            lines.append(f"  {m['side']} row {m['sheet_row']}: "
                         f"{m.get('name') or '—'} "
                         f"[{m.get('code') or '—'}]")
    if result.get("alert"):
        lines.append(f"  ALERT: {result['alert']}")
    return "\n".join(lines)
