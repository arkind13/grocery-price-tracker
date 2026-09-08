"""T8 verification driver (2026-09-08 verification round).

Single-pass battery: 387 synthetic adds (FIX-9) + variant/exact-dup rule
battery (FIX-10) + alias/keyword/NA/GONE subsets + teardown + full-grid
drift check. Driver-bug fixes applied per retest-plan §7 PLUS gspread
6.2.1 calibration (delete_rows is 1-based INCLUSIVE-INCLUSIVE — verified
empirically 2026-09-08; the old 0-based half-open formula deleted an
extra real row).

Quota safety: one process only; ≥1.3s between EVERY sheet API call;
429 backoff ×4.
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
SUMMARY = LOGDIR / "t8_summary.json"
SNAP = LOGDIR / "baselines" / "sheet_snapshot.json"
GAP = 1.3
_last = [0.0]


def T(fn, *a, **k):
    gap = time.time() - _last[0]
    if gap < GAP:
        time.sleep(GAP - gap)
    for attempt in range(4):
        try:
            r = fn(*a, **k)
            _last[0] = time.time()
            return r
        except Exception as e:
            if "429" in str(e) and attempt < 3:
                wait = 45 * (attempt + 1)
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


fails = []
ws = connect_worksheet()

# --- grid expansion (crashed run 1 hit "Max rows: 381" at add 381) ---
cur_max = 381   # observed hard ceiling (crashed run 1 APIError)
needed = 113 + 387 + 30
if cur_max < needed:
    ss = ws.spreadsheet
    ss.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": ws.id, "gridProperties": {"rowCount": needed}},
        "fields": "gridProperties.rowCount"}}]})
    print(f"grid expanded: {cur_max} -> {needed} rows (will be restored at teardown)",
          flush=True)
TARGET_MAX = {"rows": cur_max}   # teardown shrinks back to this

sheet = T(ws.get_all_values)
header, rows = sheet[0], sheet[1:]
real_rows = [(i, r) for i, r in enumerate(rows, start=2) if r and r[0].strip()]
orig_by_name = {r[0].strip(): r for _, r in real_rows}
print(f"real rows: {len(real_rows)}", flush=True)

PRICE_COL = {"woolworths": 3, "coles": 4}  # 0-based: C=WW, D=Coles

# ------------------------------------------------ Phase A: 387 adds (FIX-9)
GADGETS = ["Sparkling Water", "Rice Crackers", "Dish Soap", "Almond Milk",
           "Turmeric Powder", "Green Tea", "Pasta Sauce", "Rye Bread",
           "Olive Oil", "Chickpeas", "Basmati Rice", "Salty Crackers",
           "Coconut Yoghurt", "Butter Beans", "Tomato Paste", "Maple Syrup",
           "Peanut Butter", "Corn Flakes", "Paper Towel", "Dish Sponges",
           "Vanilla Ice Cream", "Salted Cashews", "Muesli Bars",
           "Long Life Milk", "Black Coffee"]
SIZES = ["250g", "500g", "1kg", "2L", "750mL", "12 Pack", "5 Pack",
         "300g", "150g", "4 Pack"]
synth_names = []
added = {}   # name -> (row_index, store, j)  [fix #1: store tracked IN dict]
written = 0
refused = 0
for n in range(1, 388):
    nm = f"ZZT8V {n:04d} {GADGETS[n % len(GADGETS)]} {SIZES[(n // 7) % len(SIZES)]}"
    j = n - 1
    st = "woolworths" if j % 2 == 0 else "coles"
    price = round((j % 40) + 1.5, 2)
    res = T(add_product_row, nm, st, price,
            size=SIZES[(j // 7) % len(SIZES)], worksheet=ws)
    if res.get("wrote") and res.get("row_index"):
        written += 1
        added[nm] = (res["row_index"], st, j)
        synth_names.append(nm)
    else:
        refused += 1
        fails.append(f"add refused {nm}: wrote={res.get('wrote')} "
                     f"err={res.get('error')}")
        log_op(n, nm, "add", st, "wrote", f"wrote={res.get('wrote')} "
               f"merged={res.get('merged')}", False)
    if n % 50 == 0:
        print(f"adds: {n}/387 (written={written} refused={refused})", flush=True)
print(f"PHASE A adds done: written={written} refused={refused}", flush=True)

# ---- bulk verify (fix #2: one read for the whole chunk; fix #3: numeric)
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
        fails.append(f"phantom: {nm} logged wrote but NOT on sheet")
        continue
    if i != ri:
        fails.append(f"row mismatch {nm}: logged {ri} found {i}")
    exp = round((j % 40) + 1.5, 2)
    got = vals[i - 1][PRICE_COL[st]] if len(vals[i - 1]) > PRICE_COL[st] else ""
    try:
        ok = abs(float(str(got).replace("$", "").strip()) - exp) < 0.005
    except (TypeError, ValueError):
        ok = False
    if not ok:
        fails.append(f"price verify {nm}: expected {exp} got {got!r}")
log_op("A", "PHASE-A bulk verify", "adds", "all",
       f"written==on-sheet=={len(added)}, 0 phantom",
       f"on-sheet={len(added) - ph} phantom={ph} written={written}",
       ph == 0 and written == len(added))
print(f"PHASE A verify: on-sheet={len(added)-ph} phantom={ph} written={written}",
      flush=True)

# --------------------------------- Phase B: FIX-10 variant battery (30 real)
kw_p_col = chr(ord("A") + _find_col(header, "Keywords"))
merged_n = notmerged_n = 0
for k, (ri, r) in enumerate(real_rows[:30]):
    nm = r[0].strip()
    words = nm.split()
    if k % 3 == 0 and len(words) > 1:
        variant = " ".join([words[-1]] + words[:-1])        # word-reorder
    elif k % 3 == 1:
        variant = nm.lower()                                 # lowercase
    else:
        variant = " ".join(nm.split())                       # whitespace-only
    orig = orig_by_name[nm]
    st = "woolworths" if k % 2 == 0 else "coles"
    pcol = PRICE_COL[st]
    res = T(add_product_row, variant, st, 9.99, size="unit unavailable",
            worksheet=ws)
    if res.get("merged") and res.get("row_index"):
        prow = res.get("row_index")
        # revert price + alias to pre-test values
        T(ws.update, values=[[orig[pcol] if len(orig) > pcol else ""]],
          range_name=f"{chr(ord('A') + pcol)}{prow}")
        T(ws.update, values=[[orig[15] if len(orig) > 15 else ""]],
          range_name=f"P{prow}")
        merged_n += 1
        log_op("B", variant[:45], f"variant({k % 3}) merge+revert", st,
               "merged", f"row{prow}", True)
    else:
        notmerged_n += 1
        log_op("B", variant[:45], f"variant({k % 3})", st, "EXPECTED merge",
               f"wrote={res.get('wrote')} merged={res.get('merged')}", False)
        if res.get("wrote"):
            fails.append(f"FIX-10: variant created a NEW ROW: {variant!r}")
print(f"PHASE B variants: merged={merged_n} not-merged={notmerged_n}",
      flush=True)

# ------------------------- Phase C: exact case-identical dups (refused) x10
refused_n = 0
for k in range(10):
    nm = real_rows[k][1][0].strip()
    res = T(add_product_row, nm, "woolworths" if k % 2 == 0 else "coles",
            9.99, size="unit unavailable", allow_duplicate=True, worksheet=ws)
    ok = (not res.get("wrote")) or res.get("error")
    refused_n += ok
    log_op("C", nm[:45], "exact_dup_add", "both", "refused",
           f"wrote={res.get('wrote')} err={res.get('error')}", ok)
    if not ok:
        fails.append(f"exact dup NOT refused: {nm}")
print(f"PHASE C exact dups refused: {refused_n}/10", flush=True)

# ------------------------------------------- Phase D: subsets on synth rows
alias_targets = [nm for k, nm in enumerate(synth_names) if k % 16 == 3][:25]
kw_targets = [nm for k, nm in enumerate(synth_names) if k % 16 == 5][:25]
na_targets = [nm for k, nm in enumerate(synth_names) if k % 12 == 2][:32]
gone_targets = [nm for k, nm in enumerate(synth_names) if k % 40 == 4][:10]

for nm in alias_targets:
    i = added[nm][0]
    T(_append_alias, ws, header, i, "zzt8v extra alias")
for nm in kw_targets:
    i, st, j = added[nm]
    r = T(set_store_keyword, nm, st, f"ZZT8V KEYWORD {nm}", worksheet=ws)
    if not (r.get("wrote") and not r.get("error")):
        fails.append(f"kw {nm}: {r}")
for nm in na_targets:
    i, st, j = added[nm]
    r = T(mark_not_available, nm, st, worksheet=ws)
    if not (r.get("wrote") and not r.get("error")):
        fails.append(f"na {nm}: {r}")
print("subsets written; verifying...", flush=True)

vals2 = T(ws.get_all_values)
vrow = {i: r for i, r in enumerate(vals2, start=1)}
ap = ak = an = 0
for nm in alias_targets:
    i = row_by_name[nm]
    ok = len(vrow[i]) > 15 and "zzt8v extra alias" in vrow[i][15]
    ap += ok
    if not ok:
        fails.append(f"alias verify {nm}")
for nm in kw_targets:
    i, st, j = added[nm]
    ok = len(vrow[i]) > PRICE_COL[st] + 5 and "ZZT8V KEYWORD" in vrow[i][PRICE_COL[st] + 5]
    ak += ok
    if not ok:
        fails.append(f"kw verify {nm}")
for nm in na_targets:
    i, st, j = added[nm]
    ok = len(vrow[i]) > PRICE_COL[st] and vrow[i][PRICE_COL[st]].strip().upper() == "NA"
    an += ok
    if not ok:
        fails.append(f"na verify {nm}: {vrow[i][PRICE_COL[st]:PRICE_COL[st]+1]}")
print(f"subset verify: alias {ap}/{len(alias_targets)} kw {ak}/{len(kw_targets)}"
      f" na {an}/{len(na_targets)}", flush=True)

# GONE -> resurrect (10)
gr = 0
for nm in gone_targets:
    i, st, j = added[nm]
    a1 = f"{chr(ord('A') + PRICE_COL[st])}{i}"
    T(ws.update, values=[["GONE"]], range_name=a1)
    r = T(update_single_price, nm, st, 7.77, worksheet=ws)
    vals3 = T(ws.get, a1)
    v = vals3[0][0] if vals3 and vals3[0] else ""
    ok = r.get("wrote") and v.strip().upper() != "GONE"
    gr += ok
    log_op("D", nm[:45], "gone_resurrect", a1, "cleared", v, ok)
    if not ok:
        fails.append(f"gone/resurrect {nm}: cell={v!r} res={r}")
print(f"GONE->resurrect: {gr}/{len(gone_targets)}", flush=True)

# ------------------------------------------------- Phase E: teardown
vals6 = T(ws.get_all_values)
synth_idxs = sorted((i for i, r in enumerate(vals6, start=1)
                     if r and r[0].strip().startswith("ZZT8V")))
print(f"teardown: {len(synth_idxs)} synth rows", flush=True)
contiguous = (synth_idxs == list(range(synth_idxs[0], synth_idxs[-1] + 1)))
if not contiguous:
    raise RuntimeError(f"synth rows not contiguous: {synth_idxs[:5]}...")
# gspread 6.2.1: 1-based INCLUSIVE-INCLUSIVE (calibrated 2026-09-08)
T(ws.delete_rows, synth_idxs[0], synth_idxs[-1])
try:    # restore the original grid size (metadata) after teardown
    ws.spreadsheet.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": ws.id,
                       "gridProperties": {"rowCount": TARGET_MAX["rows"]}},
        "fields": "gridProperties.rowCount"}}]})
    print(f"grid restored to {TARGET_MAX['rows']} rows", flush=True)
except Exception as e:
    fails.append(f"grid shrink-back failed: {e}")
vals7 = T(ws.get_all_values)
named = sum(1 for r in vals7[1:] if r and r[0].strip())
leftover = sum(1 for r in vals7 if r and r[0].strip().startswith("ZZT8V"))
snap = json.loads(SNAP.read_text(encoding="utf-8"))
drift = sum(1 for s, c in zip(snap, vals7) for j in range(19)
            if (list(s) + [""] * 19)[j] != (list(c) + [""] * 19)[j])
log_op("E", "teardown", "delete+drift", "all",
       f"0 leftover, 0 drift, named={len(real_rows)}",
       f"leftover={leftover} drift={drift} named={named}",
       leftover == 0 and drift == 0 and named == len(real_rows))
print(f"FINAL: named={named} leftover={leftover} drift={drift}", flush=True)

SUMMARY.write_text(json.dumps({
    "adds_written": written, "adds_refused": refused,
    "phantom": ph, "variant_merged": merged_n,
    "variant_notmerged": notmerged_n, "exact_refused": f"{refused_n}/10",
    "subset_alias": f"{ap}/{len(alias_targets)}",
    "subset_kw": f"{ak}/{len(kw_targets)}",
    "subset_na": f"{an}/{len(na_targets)}",
    "gone_resurrect": f"{gr}/{len(gone_targets)}",
    "final_named_rows": named, "final_drift_cells": drift,
    "hard_failures": fails,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print("FAILURES:", len(fails))
for f_ in fails[:40]:
    print("  -", f_)
print("DONE", flush=True)
