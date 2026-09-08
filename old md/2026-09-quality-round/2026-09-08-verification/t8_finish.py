"""T8 finisher (run 3) — Phases B-E only after the two add-run crashes.

Phase A evidence already banked: run 1 = 380 adds written / 0 refused
(grid-ceiling crash, R17); run 2 = 188 adds written / 0 refused, each
passing the new in-call read-back verify until a read-quota 429 made it
raise loudly (designed FIX-9 behavior).

This driver: FIX-10 variant battery (30 real rows), exact-dup refusals
(10), subsets on a small fresh synth pool, teardown, full-grid drift
check + grid-size restore. Throttle 2.6s (read-quota headroom).
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
GAP = 2.6
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
            msg = str(e)
            if ("429" in msg or "unreadable" in msg) and attempt < 3:
                wait = 60 * (attempt + 1)
                print(f"[quota] backing off {wait}s", flush=True)
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
sheet = T(ws.get_all_values)
header, rows = sheet[0], sheet[1:]
real_rows = [(i, r) for i, r in enumerate(rows, start=2) if r and r[0].strip()]
orig_by_name = {r[0].strip(): r for _, r in real_rows}
print(f"real rows: {len(real_rows)}", flush=True)
PRICE_COL = {"woolworths": 3, "coles": 4}

# --------------------------------- Phase B: FIX-10 variant battery (30 real)
kw_p_col = chr(ord("A") + _find_col(header, "Keywords"))
merged_n = notmerged_n = 0
for k, (ri, r) in enumerate(real_rows[:30]):
    nm = r[0].strip()
    words = nm.split()
    if k % 3 == 0 and len(words) > 1:
        variant = " ".join([words[-1]] + words[:-1])
    elif k % 3 == 1:
        variant = nm.lower()
    else:
        variant = " ".join(nm.split())
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

# ------------------- Phase D: small fresh synth pool + subsets + teardown
GADGETS = ["Sparkling Water", "Rice Crackers", "Dish Soap", "Almond Milk"]
SIZES = ["250g", "500g", "1kg", "2L"]
names, added = [], {}
for n in range(1, 33):
    nm = f"ZZT8C {n:04d} {GADGETS[n % len(GADGETS)]} {SIZES[n % len(SIZES)]}"
    j = n - 1
    st = "woolworths" if j % 2 == 0 else "coles"
    res = T(add_product_row, nm, st, round(2.5 + j, 2),
            size=SIZES[n % len(SIZES)], worksheet=ws)
    if res.get("wrote") and res.get("row_index"):
        names.append(nm)
        added[nm] = (res["row_index"], st, j)
    else:
        fails.append(f"run3 add {nm}: {res}")
print(f"fresh synth pool: {len(names)}/32", flush=True)

alias_targets = names[::8][:4]
kw_targets = names[1::8][:4]
na_targets = names[2::6][:5]
gone_targets = names[4::10][:3]

row_by_name = {}
vals = T(ws.get_all_values)
for i, r in enumerate(vals, start=1):
    if r and r[0].strip():
        row_by_name.setdefault(r[0].strip(), i)

for nm in alias_targets:
    T(_append_alias, ws, header, row_by_name[nm], "zzt8c extra alias")
for nm in kw_targets:
    i, st, j = added[nm]
    r = T(set_store_keyword, nm, st, f"ZZT8C KW {nm}", worksheet=ws)
    if not (r.get("wrote") and not r.get("error")):
        fails.append(f"kw {nm}: {r}")
for nm in na_targets:
    i, st, j = added[nm]
    r = T(mark_not_available, nm, st, worksheet=ws)
    if not (r.get("wrote") and not r.get("error")):
        fails.append(f"na {nm}: {r}")

vals2 = T(ws.get_all_values)
vrow = {i: r for i, r in enumerate(vals2, start=1)}
ap = ak = an = 0
for nm in alias_targets:
    i = row_by_name[nm]
    ok = len(vrow[i]) > 15 and "zzt8c extra alias" in vrow[i][15]
    ap += ok
    if not ok:
        fails.append(f"alias verify {nm}")
for nm in kw_targets:
    i, st, j = added[nm]
    ok = len(vrow[i]) > PRICE_COL[st] + 5 and "ZZT8C KW" in vrow[i][PRICE_COL[st] + 5]
    ak += ok
    if not ok:
        fails.append(f"kw verify {nm}")
for nm in na_targets:
    i, st, j = added[nm]
    ok = len(vrow[i]) > PRICE_COL[st] and vrow[i][PRICE_COL[st]].strip().upper() == "NA"
    an += ok
    if not ok:
        fails.append(f"na verify {nm}: cell={vrow[i][PRICE_COL[st]:PRICE_COL[st]+1]}")
print(f"subset verify: alias {ap}/{len(alias_targets)} kw {ak}/{len(kw_targets)}"
      f" na {an}/{len(na_targets)}", flush=True)

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
        fails.append(f"gone/resurrect {nm}: cell={v!r}")
print(f"GONE->resurrect: {gr}/{len(gone_targets)}", flush=True)

# ------------------------------------------------- Phase E: teardown
vals6 = T(ws.get_all_values)
synth_idxs = sorted((i for i, r in enumerate(vals6, start=1)
                     if r and r[0].strip().startswith("ZZT8C")))
print(f"teardown: {len(synth_idxs)} synth rows", flush=True)
contiguous = (synth_idxs == list(range(synth_idxs[0], synth_idxs[-1] + 1)))
if not contiguous:
    raise RuntimeError("synth rows not contiguous")
T(ws.delete_rows, synth_idxs[0], synth_idxs[-1])   # 6.2.1: inclusive 1-based
try:    # restore the original grid size (metadata)
    ws.spreadsheet.batch_update({"requests": [{"updateSheetProperties": {
        "properties": {"sheetId": ws.id,
                       "gridProperties": {"rowCount": 381}},
        "fields": "gridProperties.rowCount"}}]})
    print("grid restored to 381 rows", flush=True)
except Exception as e:
    fails.append(f"grid shrink-back failed: {e}")
vals7 = T(ws.get_all_values)
named = sum(1 for r in vals7[1:] if r and r[0].strip())
leftover = sum(1 for r in vals7 if r and r[0].strip().startswith("ZZT8"))
snap = json.loads(SNAP.read_text(encoding="utf-8"))
drift = sum(1 for s, c in zip(snap, vals7) for j in range(19)
            if (list(s) + [""] * 19)[j] != (list(c) + [""] * 19)[j])
log_op("E", "teardown", "delete+drift", "all",
       f"0 leftover, 0 drift, named={len(real_rows)}",
       f"leftover={leftover} drift={drift} named={named}",
       leftover == 0 and drift == 0 and named == len(real_rows))
print(f"FINAL: named={named} leftover={leftover} drift={drift}", flush=True)

SUMMARY.write_text(json.dumps({
    "phase_a_runs": "run1: 380 written/0 refused (grid-ceiling crash R17); "
                    "run2: 188 written/0 refused, in-call read-back verify "
                    "passed each add until read-quota 429 raised loudly",
    "adds_written_total": 568,
    "variant_merged": f"{merged_n}/30",
    "exact_refused": f"{refused_n}/10",
    "subset_alias": f"{ap}/{len(alias_targets)}",
    "subset_kw": f"{ak}/{len(kw_targets)}",
    "subset_na": f"{an}/{len(na_targets)}",
    "gone_resurrect": f"{gr}/{len(gone_targets)}",
    "final_named_rows": named, "final_drift_cells": drift,
    "hard_failures": fails,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print("FAILURES:", len(fails))
for f_ in fails[:30]:
    print("  -", f_)
print("DONE", flush=True)
