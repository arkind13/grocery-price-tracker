#!/usr/bin/env python3
"""Col Q/R/S read model, prompts, and the single P writer (§6, §8).

Single-writer rule (§8.3): EVERY 'P' write goes through
set_preferred. Wednesday sync never touches S; `prefer` is the only
writer. Sheet-side multi-P corruption is DETECTED (topmost P wins
until `prefer --code` fixes it) — never auto-deleted.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.subcategory import NEEDS_REVIEW, normalize_subcategory

SUBCATEGORY_HEADER = "Sub_Category"   # Col Q (idx 16)
ITEM_CODE_HEADER = "Item_Code"        # Col R (idx 17)
PREFERRED_HEADER = "Preferred"        # Col S (idx 18)
SUBCATEGORY_COL = 16
ITEM_CODE_COL = 17
PREFERRED_COL = 18
PREFERRED_MARK = "P"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PENDING_PATH = DATA_DIR / "shop_pending.json"  # patchable
PENDING_STALE_HOURS = 24


def _col_index(header: list, name: str):
    """Header name -> 0-based index (case-insensitive), else None."""
    for idx, cell in enumerate(header):
        if str(cell).strip().lower() == name.lower():
            return idx
    return None


def read_qrs(worksheet) -> list[dict]:
    """ONE get_all_values read -> per-row Q/R/S dicts (§9 read model).

    Rows with empty Col A are skipped. Missing Q/R/S headers yield
    empty-string fields (header-driven, robust to absence).

    Returns:
        list[dict]: {row_index, name, subcategory, item_code,
        preferred} — subcategory/``item_code`` normalised (code
        uppercased), preferred as-is ("" or "P").
    """
    values = worksheet.get_all_values()
    header = values[0] if values else []
    q = _col_index(header, SUBCATEGORY_HEADER)
    r = _col_index(header, ITEM_CODE_HEADER)
    s = _col_index(header, PREFERRED_HEADER)
    rows: list[dict] = []
    for i, row in enumerate(values[1:], start=2):
        name = str(row[0]).strip() if len(row) > 0 else ""
        if not name:
            continue
        rows.append({
            "row_index": i,
            "name": name,
            "subcategory": (normalize_subcategory(str(row[q]))
                            if q is not None and len(row) > q else ""),
            "item_code": (str(row[r]).strip().upper()
                          if r is not None and len(row) > r else ""),
            "preferred": (str(row[s]).strip()
                          if s is not None and len(row) > s else ""),
        })
    return rows


def find_by_code(rows: list[dict], code: str):
    """First row whose item_code equals `code` (uppercased), or None."""
    want = str(code or "").strip().upper()
    for row in rows:
        if row["item_code"] == want:
            return row
    return None


def get_preferred(rows: list[dict], subcategory: str):
    """The P-flagged row for a sub-category; multi-P -> TOPMOST P
    (§8.3 repair rule); no P -> None."""
    sub = normalize_subcategory(subcategory)
    flagged = [r for r in rows
               if r["subcategory"] == sub
               and r["preferred"] == PREFERRED_MARK]
    if not flagged:
        return None
    return min(flagged, key=lambda r: r["row_index"])


def list_subcategory_options(
    rows: list[dict], subcategory: str
) -> list[tuple[int, str, str]]:
    """All rows of a sub-category as (row_index, name, code) tuples."""
    sub = normalize_subcategory(subcategory)
    return [(r["row_index"], r["name"], r["item_code"])
            for r in rows if r["subcategory"] == sub]


def detect_multi_p(rows: list[dict]) -> list[dict]:
    """Sub-categories with >1 P: [{subcategory, rows: [...]}] (§8.3)."""
    by_sub: dict = {}
    for r in rows:
        if r["preferred"] == PREFERRED_MARK and r["subcategory"]:
            by_sub.setdefault(r["subcategory"], []).append(r)
    return [{"subcategory": s, "rows": rs}
            for s, rs in sorted(by_sub.items()) if len(rs) > 1]


def render_disambiguation_prompt(
    subcategory: str, options: list[tuple[int, str, str]]
) -> str:
    """EXACT §6.4 prompt text — never rephrase, never truncate names."""
    lines = [f"Sub-Category: {subcategory} - Which one would you "
             f"like to make your preferred item?"]
    for n, (_row, name, code) in enumerate(options, 1):
        lines.append(f"{n} - {name} - {code}")
    lines.append("Or: Not in list? Provide another keyword for "
                 "live search.")
    return "\n".join(lines)


def render_override_warning(name: str, subcategory: str) -> str:
    """EXACT §6.5 warning text — relay verbatim."""
    return (f"⚠️ Warning: [{name}] is not your preferred item for "
            f"sub-category [{subcategory}].\n"
            "Would you like to switch your preferred item in the "
            "sheet?\n"
            "Reply 'switch' to make it preferred, or 'keep' to "
            "continue without switching.")


def load_pending(path=None):
    """Load the halted-run file; None when absent/corrupt (D-P3)."""
    path = Path(path) if path else PENDING_PATH
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, ValueError):
        return None


def save_pending(pending: dict, path=None) -> None:
    """Atomic write (tempfile + os.replace) — queue JSON pattern."""
    path = Path(path) if path else PENDING_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(pending, fh, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def clear_pending(path=None) -> None:
    """Remove the pending file (missing_ok)."""
    path = Path(path) if path else PENDING_PATH
    try:
        path.unlink()
    except OSError:
        pass


def is_stale(pending: dict, *, now=None) -> bool:
    """True when the run started > PENDING_STALE_HOURS ago (§6.3)."""
    try:
        started = datetime.fromisoformat(str(pending.get("started_at")))
    except ValueError:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return now - started > timedelta(hours=PENDING_STALE_HOURS)


def set_preferred(worksheet, code: str) -> dict:
    """Clear-then-set ONE 'P' in `code`'s sub-category (§8.1).

    Steps: read Q+S -> compute the full S-vector for the
    sub-category's row span (non-members keep their existing S value
    so OTHER sub-categories' flags are never clobbered) -> ONE range
    write S{top}:S{bottom} -> re-read verify (exactly one P).

    Args:
        worksheet: connected gspread Worksheet.
        code: 3-letter Item-Code (case-insensitive).

    Returns:
        dict {wrote, row_index, subcategory, cleared,
        range_written, error} — error non-empty on any abort.
    """
    want = str(code or "").strip().upper()
    if not want:
        return {"wrote": False, "row_index": None, "subcategory": "",
                "cleared": 0, "range_written": "",
                "error": "code is required"}
    rows = read_qrs(worksheet)
    target = find_by_code(rows, want)
    if target is None:
        return {"wrote": False, "row_index": None, "subcategory": "",
                "cleared": 0, "range_written": "",
                "error": f"no row holds item-code {want}"}
    sub = target["subcategory"]
    if not sub:
        return {"wrote": False, "row_index": target["row_index"],
                "subcategory": "", "cleared": 0, "range_written": "",
                "error": "row has no sub-category "
                         "(run backfill-subcategories)"}
    by_index = {r["row_index"]: r for r in rows}
    members = {r["row_index"] for r in rows
               if r["subcategory"] == sub}
    top = min(members)
    bottom = max(members)
    vector: list[list[str]] = []
    cleared = 0
    for idx in range(top, bottom + 1):
        row = by_index.get(idx)
        if idx not in members:
            # Preserve other sub-categories' flags (never clobber).
            vector.append([row["preferred"] if row else ""])
        elif idx == target["row_index"]:
            vector.append([PREFERRED_MARK])
        else:
            if row and row["preferred"] == PREFERRED_MARK:
                cleared += 1
            vector.append([""])
    range_name = f"S{top}:S{bottom}"
    worksheet.update(values=vector, range_name=range_name)
    # Verify: exactly one P, on the target row (§8.1 step 4).
    check = read_qrs(worksheet)
    flags = [r for r in check
             if r["subcategory"] == sub
             and r["preferred"] == PREFERRED_MARK]
    if len(flags) != 1 or flags[0]["row_index"] != target["row_index"]:
        return {"wrote": False, "row_index": target["row_index"],
                "subcategory": sub, "cleared": cleared,
                "range_written": range_name,
                "error": "verify failed — check the sheet manually"}
    return {"wrote": True, "row_index": target["row_index"],
            "subcategory": sub, "cleared": cleared,
            "range_written": range_name, "error": ""}


def resolve_shop_items(worksheet, items: list[str]) -> dict:
    """Deterministic shop read-side state machine (§6.2 steps 2-5).

    Category mode: normalised item equals a live Col Q value OR a
    taxonomy label (core.subcategory.all_labels). Product mode:
    exact Col A match (lookup-chain Step 1 equivalence); no exact
    match falls through to compare with the raw text.

    Args:
        worksheet: connected gspread Worksheet.
        items: user/agent-normalised item strings.

    Returns:
        dict with keys:
          compare: list[(user_item, col_a_name)] — price these rows;
          halted:  list[{item, subcategory,
                       options: [(row, name, code)]}] (S1);
          cold:    list[{item, subcategory}] (S0);
          warns:   list[{item, name, subcategory}] (S5 override);
          notes:   list[str] — multi-P ⚠️ lines (§8.3).
    """
    from core.subcategory import all_labels
    rows = read_qrs(worksheet)
    norm_map = {}  # normalised Col A -> row (first wins)
    for r in rows:
        key = normalize_subcategory(r["name"])
        norm_map.setdefault(key, r)
    sub_labels = {normalize_subcategory(x) for x in all_labels()}
    for r in rows:
        if r["subcategory"]:
            sub_labels.add(r["subcategory"])

    compare: list = []
    halted: list = []
    cold: list = []
    warns: list = []
    notes: list = []
    for item in items:
        key = normalize_subcategory(item)
        if key in sub_labels:  # ---- category mode (S4/S1/S0) ----
            members = [r for r in rows if r["subcategory"] == key]
            if not members:
                cold.append({"item": item, "subcategory": key})
                continue
            flagged = [r for r in members
                       if r["preferred"] == PREFERRED_MARK]
            if len(flagged) > 1:
                topmost = min(flagged,
                              key=lambda r: r["row_index"])
                notes.append(
                    f"⚠️ sub-category '{key}' has "
                    f"{len(flagged)} P flags — topmost (row "
                    f"{topmost['row_index']}) wins until "
                    f"'prefer --code {topmost['item_code']}' fixes it")
                flagged = [topmost]
            if flagged:
                compare.append((item, flagged[0]["name"]))
            else:
                halted.append({
                    "item": item, "subcategory": key,
                    "options": [(r["row_index"], r["name"],
                                 r["item_code"])
                                for r in members],
                })
        else:  # ---- product mode (S5) ----
            hit = norm_map.get(key)
            if hit is not None and hit["subcategory"]:
                pref = get_preferred(rows, hit["subcategory"])
                if pref is None or pref["row_index"] != \
                        hit["row_index"]:
                    warns.append({"item": item, "name": hit["name"],
                                  "subcategory":
                                  hit["subcategory"]})
            compare.append((item, hit["name"] if hit else item))
    return {"compare": compare, "halted": halted, "cold": cold,
            "warns": warns, "notes": notes}
