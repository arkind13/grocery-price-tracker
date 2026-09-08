"""T8 round-B2 driver, Phase B: variant battery (R2-3/D22 live), exact dups,
subsets (D16), teardown + drift check. Run AFTER t8r2_a.py.

Phase B adds a dedicated D22 variant: 'pack Evamay Pads With Wings Super 14'
(the exact reorder that appended a dup row in the prior round) — must MERGE.
Merge reverts restore price col + P alias + H timestamp.
Teardown: contiguity assert, gspread 6.2.1 inclusive delete_rows, grid
restore to 380, full-grid drift vs baselines/sheet_snapshot.json.
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
sheet = T(ws.get_all_values)
header, rows = sheet[0], sheet[1:]
real_rows = [(i, r) for i, r in enumerate(rows, start=2) if r and r[0].strip()]
orig_by_name = {r[0].strip(): r for _, r in real_rows}
print(f"real rows: {len(real_rows)}", flush=True)
PRICE_COL = {"woolworths": 3, "coles": 4}

# ---------------- Phase B: variant battery (R2-3/D22 live) — 30 real rows
kw_p_col = chr(ord("A") + _find_col(header, "Keywords"))
merged_n = notmerged_n = 0
d22_done = False
for k, (ri, r) in enumerate(real_rows[:30]):
    nm = r[0].strip()
    words = nm.split()
    if k % 3 == 0 and len(words) > 1:
        variant = " ".join([words[-1]] + words[:-1])        # word-reorder
    elif k % 3 == 1:
        variant = nm.lower()                                 # lowercase
    else:
        variant = " ".join(nm.split())                       # whitespace-only
    if not d22_done and nm == "Evamay Pads With Wings Super 14 pack":
        variant = "pack Evamay Pads With Wings Super 14"     # exact D22 shape
        d22_done = True
    orig = orig_by_name[nm]
    st = "woolworths" if k % 2 == 0 else "coles"
    pcol = PRICE_COL[st]
    res = T(add_product_row, variant, st, 9.99, size="unit unavailable",
            worksheet=ws)
    if res.get("merged") and res.get("row_index"):
        prow = res.get("row_index")
        # revert price + alias + H timestamp to pre-test values
        T(ws.update, values=[[orig[pcol] if len(orig) > pcol else ""]],
          range_name=f"{chr(ord('A') + pcol)}{prow}")
        T(ws.update, values=[[orig[15] if len(orig) > 15 else ""]],
          range_name=f"P{prow}")
        T(ws.update, values=[[orig[7] if len(orig) > 7 else ""]],
          range_name=f"H{prow}")
        merged_n += 1
        log_op("B", variant[:45], f"variant({k % 3}) merge+revert", st,
               "merged", f"row{prow}", True)
    else:
        notmerged_n += 1
        log_op("B", variant[:45], f"variant({k % 3})", st, "EXPECTED merge",
               f"wrote={res.get('wrote')} merged={res.get('merged')}", False)
        if res.get("wrote"):
            fails.append(f"R2-3: variant created a NEW ROW: {variant!r}")
print(f"PHASE B variants: merged={merged_n} not-merged={notmerged_n} "
      f"d22_variant={'yes' if d22_done else 'MISSING'}", flush=True)

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

# ------------------------- Phase D: subsets on the Phase-A synth pool
state = json.loads((LOGDIR / "phase_a_state.json").read_text(encoding="utf-8"))
added = {k: tuple(v) for k, v in state["added"].items()}
synth_names = state["added_names"]

alias_targets = [nm for k, nm in enumerate(synth_names) if k % 16 == 3][:25]
kw_targets = [nm for k, nm in enumerate(synth_names) if k % 16 == 5][:25]
na_targets = [nm for k, nm in enumerate(synth_names) if k % 12 == 2][:32]
gone_targets = [nm for k, nm in enumerate(synth_names) if k % 40 == 4][:10]

for nm in alias_targets:
    i = added[nm][0]
    T(_append_alias, ws, header, i, "zzt8r extra alias")
for nm in kw_targets:
    i, st, j = added[nm]
    r = T(set_store_keyword, nm, st, f"ZZT8R KEYWORD {nm}", worksheet=ws)
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
row_by_name = {}
for i, r in enumerate(vals2, start=1):
    if r and r[0].strip():
        row_by_name.setdefault(r[0].strip(), i)
ap = ak = an = 0
for nm in alias_targets:
    i = row_by_name[nm]
    ok = len(vrow[i]) > 15 and "zzt8r extra alias" in vrow[i][15]
    ap += ok
    if not ok:
        fails.append(f"alias verify {nm}")
for nm in kw_targets:
    i, st, j = added[nm]
    ok = len(vrow[i]) > PRICE_COL[st] + 5 and "ZZT8R KEYWORD" in vrow[i][PRICE_COL[st] + 5]
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
                     if r and r[0].strip().startswith("ZZT8R")))
print(f"teardown: {len(synth_idxs)} synth rows", flush=True)
contiguous = (synth_idxs == list(range(synth_idxs[0], synth_idxs[-1] + 1)))
if not contiguous:
    raise RuntimeError(f"synth rows not contiguous: {synth_idxs[:5]}...")
T(ws.delete_rows, synth_idxs[0], synth_idxs[-1])   # 6.2.1: 1-based inclusive
time.sleep(2.0)
try:    # restore the original grid size (metadata): baseline was 380 rows
    meta = ws.spreadsheet.fetch_sheet_metadata()
    grid_rows = next(sh["properties"]["gridProperties"]["rowCount"]
                     for sh in meta["sheets"]
                     if sh["properties"]["sheetId"] == ws.id)
    target = 380
    if grid_rows > target:
        ws.spreadsheet.batch_update({"requests": [{
            "updateSheetProperties": {
                "properties": {"sheetId": ws.id,
                               "gridProperties": {"rowCount": target}},
                "fields": "gridProperties.rowCount"}}]})
        print(f"grid restored {grid_rows} -> {target} rows", flush=True)
    else:
        print(f"grid at {grid_rows} rows (no shrink needed)", flush=True)
except Exception as e:
    fails.append(f"grid shrink-back failed: {e}")
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
print(f"FINAL: named={named} leftover={leftover} drift={len(drift)}",
      flush=True)
for d in drift[:20]:
    print(f"  drift R{d[0]}C{d[1]}", flush=True)

(LOGDIR / "t8r2_summary.json").write_text(json.dumps({
    "phase_a": {k: state[k] for k in ("written", "refused", "phantom",
                                      "grid_rows_after")},
    "variant_merged": merged_n, "variant_notmerged": notmerged_n,
    "d22_variant_included": d22_done,
    "exact_refused": f"{refused_n}/10",
    "subset_alias": f"{ap}/{len(alias_targets)}",
    "subset_kw": f"{ak}/{len(kw_targets)}",
    "subset_na": f"{an}/{len(na_targets)}",
    "gone_resurrect": f"{gr}/{len(gone_targets)}",
    "final_named_rows": named, "final_drift_cells": len(drift),
    "hard_failures": fails,
}, ensure_ascii=False, indent=1), encoding="utf-8")
print("FAILURES:", len(fails))
for f_ in fails[:40]:
    print("  -", f_)
print("DONE", flush=True)
