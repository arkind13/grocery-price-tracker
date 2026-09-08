"""T8 round-B2 CLEANUP + remaining battery.

R2-11 was proven STILL BROKEN (guard reads nonexistent gspread .rows;
raw APIError escapes — see outputs/S1_R2-11_guard_skipped_live.txt and
the two crash logs). This driver: manually restore the grid to 380 (the
expansion the guard should have done), then run the remaining elements:
10 D16 adds (in-call read-back verify), bulk verify of all synth rows,
Phase B variants incl. exact D22, exact dups, subsets, teardown, drift.
"""
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker")
from core.sheets_client import connect_worksheet
from core.sheets_sync import (add_product_row, mark_not_available,
                              set_store_keyword, _append_alias,
                              update_single_price, _find_col)

LOGDIR = Path(__file__).parent
OPS = LOGDIR / "t8_ops_log.csv"
GAP = 2.0
_last = [0.0]


def T(fn, *a, **k):
    gap = time.time() - _last[0]
    if gap < GAP:
        time.sleep(GAP - gap)
    for attempt in range(6):
        try:
            r = fn(*a, **k)
            _last[0] = time.time()
            return r
        except Exception as e:
            if "429" in str(e) and attempt < 5:
                wait = 70 * (attempt + 1)
                print(f"[429] backing off {wait}s", flush=True)
                time.sleep(wait)
            else:
                raise


def log_op(item_no, name, op, target, expected, actual, ok):
    with OPS.open("a", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["ts", "item_no", "item", "op", "target",
                        "expected", "actual", "pass"])
        w.writerow([datetime.now().strftime("%H:%M:%S"), item_no, name[:60],
                    op, target, str(expected)[:70], str(actual)[:70],
                    "PASS" if ok else "FAIL"])


def grid_rows_of(ws):
    meta = ws.spreadsheet.fetch_sheet_metadata()
    return next(sh["properties"]["gridProperties"]["rowCount"]
                for sh in meta["sheets"] if sh["properties"]["sheetId"] == ws.id)


fails = []
ws = connect_worksheet()
gr = grid_rows_of(ws)
if gr < 380:
    T(ws.spreadsheet.batch_update, {"requests": [{
        "updateSheetProperties": {
            "properties": {"sheetId": ws.id, "gridProperties": {"rowCount": 380}},
            "fields": "gridProperties.rowCount"}}]})
    print(f"grid manually restored {gr} -> 380 (the expansion R2-11's "
          f"guard should have performed)", flush=True)
sheet = T(ws.get_all_values)
header, rows = sheet[0], sheet[1:]
real_rows = [(i, r) for i, r in enumerate(rows, start=2)
             if r and r[0].strip() and not r[0].strip().startswith("ZZT8R")]
orig_by_name = {r[0].strip(): r for _, r in real_rows}
added = {}
for i, r in enumerate(sheet, start=1):
    if r and r[0].strip().startswith("ZZT8R"):
        nm = r[0].strip()
        j = int(nm.split()[1]) - 1
        added[nm] = (i, "woolworths" if j % 2 == 0 else "coles", j)
print(f"real rows: {len(real_rows)}; synth on sheet: {len(added)}", flush=True)
PRICE_COL = {"woolworths": 3, "coles": 4}

GADGETS = ["Sparkling Water", "Rice Crackers", "Dish Soap", "Almond Milk",
           "Turmeric Powder", "Green Tea", "Pasta Sauce", "Rye Bread",
           "Olive Oil", "Chickpeas", "Basmati Rice", "Salty Crackers",
           "Coconut Yoghurt", "Butter Beans", "Tomato Paste", "Maple Syrup",
           "Peanut Butter", "Corn Flakes", "Paper Towel", "Dish Sponges",
           "Vanilla Ice Cream", "Salted Cashews", "Muesli Bars",
           "Long Life Milk", "Black Coffee"]
SIZES = ["250g", "500g", "1kg", "2L", "750mL", "12 Pack", "5 Pack",
         "300g", "150g", "4 Pack"]

start_n = max(int(n.split()[1]) for n in added) + 1
written = refused = 0
for n in range(start_n, start_n + 10):
    nm = f"ZZT8R {n:04d} {GADGETS[n % len(GADGETS)]} {SIZES[(n // 7) % len(SIZES)]}"
    j = n - 1
    st = "woolworths" if j % 2 == 0 else "coles"
    price = round((j % 40) + 1.5, 2)
    res = T(add_product_row, nm, st, price,
            size=SIZES[(j // 7) % len(SIZES)], worksheet=ws)
    if res.get("wrote") and res.get("row_index"):
        written += 1
        added[nm] = (res["row_index"], st, j)
    else:
        refused += 1
        fails.append(f"add refused {nm}: {res.get('error')}")
print(f"adds: new={written} refused={refused} total synth={len(added)}",
      flush=True)

vals = T(ws.get_all_values)
row_by_name = {}
for i, r in enumerate(vals, start=1):
    if r and r[0].strip():
        row_by_name.setdefault(r[0].strip(), i)
ph = 0
for nm, (ri, st, j) in added.items():
    i = row_by_name.get(nm)
    if i is None:
        ph += 1
        log_op("A", nm, "phantom-check", "sheet", "on sheet", "MISSING", False)
        continue
    exp = round((j % 40) + 1.5, 2)
    got = vals[i - 1][PRICE_COL[st]] if len(vals[i - 1]) > PRICE_COL[st] else ""
    try:
        ok = abs(float(str(got).replace("$", "").strip()) - exp) < 0.005
    except (TypeError, ValueError):
        ok = False
    if not ok:
        log_op("A", nm, "price-verify", st, str(exp), repr(got), False)
log_op("A", "bulk verify", "adds", "all",
       f"on-sheet=={len(added)}, 0 phantom", f"phantom={ph}", ph == 0)
print(f"bulk verify: total={len(added)} phantom={ph}", flush=True)

# ---- Phase B: variants incl. exact D22 ----
merged_n = notmerged_n = 0
d22_logged = False
for k, (ri, r) in enumerate(real_rows[:16]):
    nm = r[0].strip()
    words = nm.split()
    if k % 3 == 0 and len(words) > 1:
        variant = " ".join([words[-1]] + words[:-1])
    elif k % 3 == 1:
        variant = nm.lower()
    else:
        variant = " ".join(nm.split())
    is_d22 = False
    if not d22_logged and nm == "Evamay Pads With Wings Super 14 pack":
        variant = "pack Evamay Pads With Wings Super 14"
        is_d22 = True
    orig = orig_by_name[nm]
    st = "woolworths" if k % 2 == 0 else "coles"
    pcol = PRICE_COL[st]
    res = T(add_product_row, variant, st, 9.99, size="unit unavailable",
            worksheet=ws)
    if res.get("merged") and res.get("row_index"):
        prow = res.get("row_index")
        T(ws.update, values=[[orig[pcol] if len(orig) > pcol else ""]],
          range_name=f"{chr(ord('A') + pcol)}{prow}")
        T(ws.update, values=[[orig[15] if len(orig) > 15 else ""]],
          range_name=f"P{prow}")
        T(ws.update, values=[[orig[7] if len(orig) > 7 else ""]],
          range_name=f"H{prow}")
        merged_n += 1
        if is_d22:
            d22_logged = True
        log_op("B", variant[:45],
               f"variant({k % 3}){' **D22**' if is_d22 else ''} merge+revert",
               st, "merged", f"row{prow}", True)
    else:
        notmerged_n += 1
        log_op("B", variant[:45],
               f"variant({k % 3}){' **D22**' if is_d22 else ''}",
               st, "EXPECTED merge",
               f"wrote={res.get('wrote')} merged={res.get('merged')}", False)
        if res.get("wrote"):
            fails.append(f"R2-3: variant created a NEW ROW: {variant!r}")
print(f"PHASE B: merged={merged_n} not-merged={notmerged_n} "
      f"d22 exercised={d22_logged}", flush=True)

# ---- Phase C: 5 exact dups ----
refused_n = 0
for k in range(5):
    nm = real_rows[k][1][0].strip()
    res = T(add_product_row, nm, "woolworths" if k % 2 == 0 else "coles",
            9.99, size="unit unavailable", allow_duplicate=True, worksheet=ws)
    ok = (not res.get("wrote")) or res.get("error")
    refused_n += ok
    log_op("C", nm[:45], "exact_dup_add", "both", "refused",
           f"wrote={res.get('wrote')}", ok)
    if not ok:
        fails.append(f"exact dup NOT refused: {nm}")
print(f"PHASE C exact dups refused: {refused_n}/5", flush=True)

# ---- Phase D subsets ----
synth_names = sorted(added, key=lambda n: int(n.split()[1]))
alias_targets = synth_names[2::20][:5]
kw_targets = synth_names[6::20][:5]
na_targets = synth_names[10::14][:7]
gone_targets = synth_names[14::25][:4]
for nm in alias_targets:
    T(_append_alias, ws, header, added[nm][0], "zzt8r extra alias")
for nm in kw_targets:
    i, st, j = added[nm]
    T(set_store_keyword, nm, st, f"ZZT8R KEYWORD {nm}", worksheet=ws)
for nm in na_targets:
    i, st, j = added[nm]
    r = T(mark_not_available, nm, st, worksheet=ws)
    if not (r.get("wrote") and not r.get("error")):
        fails.append(f"na {nm}: {r}")
vals2 = T(ws.get_all_values)
vrow = {i: r for i, r in enumerate(vals2, start=1)}
rbn = {}
for i, r in enumerate(vals2, start=1):
    if r and r[0].strip():
        rbn.setdefault(r[0].strip(), i)
ap = sum(1 for nm in alias_targets
         if len(vrow[rbn[nm]]) > 15 and "zzt8r extra alias" in vrow[rbn[nm]][15])
ak = sum(1 for nm in kw_targets
         if len(vrow[rbn[nm]]) > PRICE_COL[added[nm][1]] + 5
         and "ZZT8R KEYWORD" in vrow[rbn[nm]][PRICE_COL[added[nm][1]] + 5])
an = sum(1 for nm in na_targets
         if len(vrow[rbn[nm]]) > PRICE_COL[added[nm][1]]
         and vrow[rbn[nm]][PRICE_COL[added[nm][1]]].strip().upper() == "NA")
print(f"subset verify: alias {ap}/{len(alias_targets)} kw {ak}/{len(kw_targets)}"
      f" na {an}/{len(na_targets)}", flush=True)
if (ap, ak, an) != (len(alias_targets), len(kw_targets), len(na_targets)):
    fails.append(f"subset shortfall: {ap}/{ak}/{an}")

gr2 = 0
for nm in gone_targets:
    i, st, j = added[nm]
    a1 = f"{chr(ord('A') + PRICE_COL[st])}{i}"
    T(ws.update, values=[["GONE"]], range_name=a1)
    r = T(update_single_price, nm, st, 7.77, worksheet=ws)
    vals3 = T(ws.get, a1)
    v = vals3[0][0] if vals3 and vals3[0] else ""
    ok = r.get("wrote") and v.strip().upper() != "GONE"
    gr2 += ok
    log_op("D", nm[:45], "gone_resurrect", a1, "cleared", v, ok)
print(f"GONE->resurrect: {gr2}/{len(gone_targets)}", flush=True)

# ---- teardown ----
vals6 = T(ws.get_all_values)
synth_idxs = sorted((i for i, r in enumerate(vals6, start=1)
                     if r and r[0].strip().startswith("ZZT8R")))
print(f"teardown: {len(synth_idxs)} synth rows", flush=True)
if synth_idxs != list(range(synth_idxs[0], synth_idxs[-1] + 1)):
    raise RuntimeError("synth rows not contiguous")
T(ws.delete_rows, synth_idxs[0], synth_idxs[-1])   # 6.2.1 inclusive
time.sleep(2.0)
gr_now = grid_rows_of(ws)
if gr_now != 380:
    T(ws.spreadsheet.batch_update, {"requests": [{
        "updateSheetProperties": {
            "properties": {"sheetId": ws.id, "gridProperties": {"rowCount": 380}},
            "fields": "gridProperties.rowCount"}}]})
    print(f"grid restored {gr_now} -> 380", flush=True)
else:
    print("grid already 380", flush=True)
vals7 = T(ws.get_all_values)
named = sum(1 for r in vals7[1:] if r and r[0].strip())
leftover = sum(1 for r in vals7 if r and r[0].strip().startswith("ZZT8"))
snap = json.loads((LOGDIR.parent / "baselines" / "sheet_snapshot.json")
                  .read_text(encoding="utf-8"))
drift = [(r + 1, c + 1) for r in range(max(len(snap), len(vals7)))
         for c in range(max(len(snap[r]) if r < len(snap) else 0,
                            len(vals7[r]) if r < len(vals7) else 0))
         if (snap[r][c] if r < len(snap) and c < len(snap[r]) else "")
         != (vals7[r][c] if r < len(vals7) and c < len(vals7[r]) else "")]
log_op("E", "teardown", "delete+drift", "all",
       f"0 leftover, 0 drift, named={len(real_rows)}",
       f"leftover={leftover} drift={len(drift)} named={named}",
       leftover == 0 and not drift and named == len(real_rows))
print(f"FINAL: named={named} leftover={leftover} drift={len(drift)}", flush=True)
for d in drift[:20]:
    print(f"  drift R{d[0]}C{d[1]}", flush=True)

(LOGDIR / "t8r2_summary.json").write_text(json.dumps({
    "mode": "cleanup + remaining battery (R2-11 proven broken separately)",
    "adds_new": written, "adds_refused": refused, "phantom": ph,
    "synth_total": len(added),
    "variant_merged": merged_n, "variant_notmerged": notmerged_n,
    "d22_exercised": d22_logged,
    "exact_refused": f"{refused_n}/5",
    "subset_alias": f"{ap}/{len(alias_targets)}",
    "subset_kw": f"{ak}/{len(kw_targets)}",
    "subset_na": f"{an}/{len(na_targets)}",
    "gone_resurrect": f"{gr2}/{len(gone_targets)}",
    "final_named_rows": named, "final_drift_cells": len(drift),
    "hard_failures": fails,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print("FAILURES:", len(fails))
for f_ in fails[:40]:
    print("  -", f_)
print("DONE", flush=True)
