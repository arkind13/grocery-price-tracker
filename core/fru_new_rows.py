#!/usr/bin/env python3
"""One-off (2026-10-25, user ask): Fruitopia permanent prices onto the sheet.

1. existing rows — Fruitopia perm (LD col G):
   Lebanese Cucumbers /kg  -> 2.99   (row-aligned with PM)
   Banana /kg              -> 5.99
2. NEW rows (bottom of BOTH tabs, row-for-row, fresh Item_Code,
   _mirror_new_rows' shape) with WW col D per the new standing rule
   (catalogue price where stocked, honest basis, blank when not stocked):
   Water 12 pcs /ea        -> FRU perm 9.99, comment "[FRU] minimum buy 3"
   Okra Tray /ea           -> FRU perm 3.99            (WW: not stocked)
   Watermelon Seedless Cut /ea -> FRU perm 3.99        (WW: $8.58/quarter)
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")
from core import item_codes, sheets_client  # noqa: E402

FRU_PERM_EXISTING = {  # LD row -> (col G value, note)
    287: ("2.99", "Lebanese Cucumbers /kg"),
    292: ("5.99", "Banana /kg"),
}
NEW_ROWS = [
    # name, PM category, sub, FRU perm, comments, WW col D or None
    ("Water 12 pcs /ea", "drinks", "fruit & veg", "9.99", "[FRU] minimum buy 3", None),
    ("Okra Tray /ea", "vegetables", "fruit & veg", "3.99", "", None),
    ("Watermelon Seedless Cut /ea", "fruits", "fruit & veg", "3.99", "", "$8.58/quarter"),
]


def main() -> None:
    ss = sheets_client.connect_spreadsheet()
    # make room: the sheet grid needs rows for the bottom-append (row-for-row)
    import gspread  # noqa: F401
    pm_ws = ss.worksheet("Products_Master")
    ld_ws = ss.worksheet("Local_Deals")
    need = max(len(pm_ws.get_all_values()), len(ld_ws.get_all_values())) + len(NEW_ROWS) + 1
    if pm_ws.row_count < need:
        pm_ws.resize(rows=need)
    if ld_ws.row_count < need:
        ld_ws.resize(rows=need)
    pm = ss.worksheet("Products_Master")
    ld = ss.worksheet("Local_Deals")
    pm_grid = pm.get_all_values()
    ld_grid = ld.get_all_values()
    last = max(len(pm_grid), len(ld_grid))
    print(f"PM rows: {len(pm_grid)} | LD rows: {len(ld_grid)} -> appending from row {last + 1}")

    taken = item_codes.retired_codes(item_codes.load_registry())
    for r in pm_grid[1:]:
        c = str(r[11]).strip().upper() if len(r) > 11 else ""
        if c:
            taken.add(c)

    # 1) Fruitopia perm on existing rows (LD col G)
    for row_idx, (val, label) in FRU_PERM_EXISTING.items():
        print(f"LD G{row_idx} = {val}  ({label})")
        ld.update(f"G{row_idx}", [[val]])
        time.sleep(1.1)

    # 2) new rows on BOTH tabs (row-for-row), fresh codes
    sheet_id = item_codes._spreadsheet_id(pm)
    pending = []
    for i, (name, cat, sub, fru, comment, ww) in enumerate(NEW_ROWS):
        code = item_codes.generate_codes(taken, 1, seed=f"fru:{name}")[0]
        taken.add(code)
        row_idx = last + 1 + i
        # LD: Product, Category, ..., G=FRU perm, L=Comments, M=code
        ld_row = [""] * 13
        ld_row[0], ld_row[1] = name, cat
        ld_row[6] = fru
        ld_row[11] = comment
        ld_row[12] = code
        ld.update(f"A{row_idx}:M{row_idx}", [ld_row])
        time.sleep(1.1)
        # PM: name, category, size, D=WW price?, ..., K=sub, L=code
        pm_row = [""] * 12
        pm_row[0], pm_row[1] = name, cat
        if ww:
            pm_row[3] = ww
            pm_row[5] = "2026-10-25"
        pm_row[10], pm_row[11] = sub, code
        pm.update(f"A{row_idx}:L{row_idx}", [pm_row])
        time.sleep(1.1)
        pending.append((code, row_idx))
        print(f"row {row_idx}: {name}  FRU {fru}  WW={ww or '—'}  code {code}")

    for code, row_idx in pending:
        item_codes.confirm_code(code, row_idx, spreadsheet_id=sheet_id)
    print("codes confirmed:", [c for c, _ in pending])


if __name__ == "__main__":
    main()
