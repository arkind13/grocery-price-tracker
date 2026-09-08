"""T8 v3 — remaining subsets + rule battery + teardown, globally throttled.

Covers what crash #2 skipped: alias/keyword/NA/GONE subsets, the
one-line-rule battery, and teardown + full-grid drift check. Adds on
top of the ops already logged by v2 (adds + updates, all verified).
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
                              set_store_keyword, _append_alias, _find_col)

LOGDIR = Path(r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker\data\test_logs\2026-09-08-comprehensive")
OPS = LOGDIR / "t8_ops_log.csv"
SNAP = LOGDIR / "baselines" / "t8_sheet_snapshot.json"
GAP = 1.3
_last = [0.0]


def T(fn, *a, **k):
    """Throttle EVERY sheet API call; 429 backoff."""
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
        w.writerow([datetime.now().strftime("%H:%M:%S"), item_no, name[:60], op,
                    target, str(expected)[:70], str(actual)[:70], "PASS" if ok else "FAIL"])


fails = []
ws = connect_worksheet()
sheet = T(ws.get_all_values)
header, rows = sheet[0], sheet[1:]
real_rows = [(i, r) for i, r in enumerate(rows, start=2) if r and r[0].strip()]
orig_by_name = {r[0].strip(): r for r in rows if r and r[0].strip()}
print(f"real rows: {len(real_rows)}", flush=True)

# ---- fresh synthetic pool for the subset/rule battery (v2 covered adds+updates on 387)
from core.sheets_sync import add_product_row as _apr
GADGETS = ["Sea Salt", "Rice Crackers", "Dish Soap", "Almond Milk", "Turmeric Powder",
           "Green Tea", "Pasta Sauce", "Rye Bread", "Olive Oil", "Chickpeas", "Basmati Rice",
           "Salty Crackers", "Coconut Yoghurt", "Butter Beans", "Tomato Paste", "Maple Syrup",
           "Peanut Butter", "Corn Flakes", "Paper Towel", "Dish Sponges", "Vanilla Ice Cream",
           "Salted Cashews", "Muesli Bars", "Long Life Milk", "Black Coffee"]
SIZES = ["250g", "500g", "1kg", "2L", "750mL", "12 Pack", "5 Pack", "300g", "150g", "4 Pack"]
PRICE_COL = {"woolworths": 3, "coles": 4}
names = []
rowidx_by_name = {}
store_of_j = {}
for n in range(1, 198):
    nm = f"ZZT8B {n:04d} {GADGETS[n % len(GADGETS)]} {SIZES[(n // 7) % len(SIZES)]}"
    j = n - 1
    st = "woolworths" if j % 2 == 0 else "coles"
    res = T(_apr, nm, st, round((j % 40) + 1.5, 2), size=SIZES[(j // 7) % len(SIZES)], worksheet=ws)
    if res.get("wrote") and res.get("row_index"):
        names.append(nm)
        rowidx_by_name[nm] = res["row_index"]
        store_of_j[nm] = st
    else:
        fails.append(f"v3 add {nm}: {res}")
print(f"fresh synth rows added: {len(names)}/197", flush=True)

# ---------------------------------------------------------- alias subset (50)
kw_p_col = chr(ord("A") + _find_col(header, "Keywords"))
alias_targets = [nm for k, nm in enumerate(names) if k % 8 == 3][:50]
before_by_row = {}
for nm in alias_targets:
    i = rowidx_by_name[nm]
    before_by_row[i] = T(ws.get, f"{kw_p_col}{i}")
for nm in alias_targets:
    i = rowidx_by_name[nm]
    out = T(_append_alias, ws, header, i, "zzt8 extra alias")
    log_op("alias", nm, "append_alias", f"{kw_p_col}{i}", "appended", str(out), out != "dup")
print("alias subset done", flush=True)

# ---------------------------------------------------------- keyword subset (50)
kw_targets = [nm for k, nm in enumerate(names) if k % 8 == 5][:50]
for nm in kw_targets:
    i = rowidx_by_name[nm]
    st = store_of_j[nm]
    r = T(set_store_keyword, nm, st, f"ZZT8 STORE KEYWORD for {nm}", worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op("kw", nm, f"set_keyword:{st}", f"row{r.get('row_index')}", "wrote",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)
    if not ok:
        fails.append(f"kw {nm}: {r}")
print("keyword subset done", flush=True)

# ---------------------------------------------------------- NA subset (60)
na_targets = [nm for k, nm in enumerate(names) if k % 6 == 2][:60]
for nm in na_targets:
    i = rowidx_by_name[nm]
    st = store_of_j[nm]
    r = T(mark_not_available, nm, st, worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op("na", nm, f"mark_na:{st}", f"row{r.get('row_index')}", "NA written",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)
    if not ok:
        fails.append(f"na {nm}: {r}")
print("NA subset done", flush=True)

# ---------------------------------------------------------- GONE -> resurrect (19)
gone_targets = [nm for k, nm in enumerate(names) if k % 20 == 4][:19]
for nm in gone_targets:
    i = rowidx_by_name[nm]
    st = store_of_j[nm]
    a1 = f"{chr(ord('A')+PRICE_COL[st])}{i}"
    T(ws.update, values=[["GONE"]], range_name=a1)
    back = T(ws.get, a1)
    back_v = back[0][0] if back and back[0] else ""
    log_op("gone", nm, "stamp_gone", a1, "GONE", back_v, back_v == "GONE")
    from core.sheets_sync import update_single_price
    r = T(update_single_price, nm, st, 7.77, worksheet=ws)
    back2 = T(ws.get, a1)
    back2_v = back2[0][0] if back2 and back2[0] else ""
    ok = r.get("wrote") and back2_v != "GONE"
    log_op("gone", nm, "resurrect_via_update", a1, "cleared", back2_v, ok)
    if not ok:
        fails.append(f"gone/resurrect {nm}: {r}")
print("gone/resurrect subset done", flush=True)

# ---------------------------------------------------------- bulk verify subsets
vals = T(ws.get_all_values)
vrow = {i: r for i, r in enumerate(vals, start=1)}
ap = ak = an = 0
for nm in alias_targets:
    i = rowidx_by_name[nm]
    ok = (kw_p_col.lower() in ("p",)) and len(vrow[i]) > 15 and "zzt8 extra alias" in vrow[i][15]
    ap += ok
    if not ok:
        fails.append(f"alias verify {nm}")
for nm in kw_targets:
    i = rowidx_by_name[nm]
    st = store_of_j[nm]
    ok = len(vrow[i]) > PRICE_COL[st] and "ZZT8 STORE KEYWORD" in vrow[i][PRICE_COL[st] + 5]
    ak += ok
    if not ok:
        fails.append(f"kw verify {nm}: cell={vrow[i][PRICE_COL[st]+5] if len(vrow[i])>PRICE_COL[st]+5 else '?'}")
for nm in na_targets:
    i = rowidx_by_name[nm]
    st = store_of_j[nm]
    ok = (len(vrow[i]) > PRICE_COL[st] and vrow[i][PRICE_COL[st]].strip().upper() == "NA")
    an += ok
    if not ok:
        fails.append(f"na verify {nm}")
print(f"subset verify: alias {ap}/{len(alias_targets)} kw {ak}/{len(kw_targets)} na {an}/{len(na_targets)}", flush=True)

# ---------------------------------------------------------- rule battery (phase 3)
merged_n = refused_n = 0
for k, (row_i, r_) in enumerate(real_rows[:30]):
    nm = r_[0].strip()
    words = nm.split()
    variant = (" ".join([words[-1]] + words[:-1]) if k % 2 == 0 and len(words) > 1 else nm.lower())
    orig = orig_by_name[nm]
    st = "woolworths" if k % 2 == 0 else "coles"
    pcol = PRICE_COL[st]
    res = T(add_product_row, variant, st, 9.99, size="unit unavailable", worksheet=ws)
    if res.get("merged") and res.get("row_index"):
        prow = res.get("row_index")
        T(ws.update, values=[[orig[pcol] if len(orig) > pcol else ""]], range_name=f"{chr(ord('A')+pcol)}{prow}")
        T(ws.update, values=[[orig[15] if len(orig) > 15 else ""]], range_name=f"P{prow}")
        merged_n += 1
        log_op("V", variant[:45], f"variant_add(merged row{prow}, reverted)", st, "merged", "ok", True)
    else:
        log_op("V", variant[:45], f"variant_add(row{res.get('row_index')})", st,
               "EXPECTED merge", f"wrote={res.get('wrote')} merged={res.get('merged')}", bool(res.get("merged")))
        if res.get("wrote") and res.get("row_index"):
            fails.append(f"variant did NOT merge: {variant!r} -> row {res.get('row_index')}")
for k, (row_i, r_) in enumerate(real_rows[:10]):
    nm = r_[0].strip()
    res = T(add_product_row, nm, "woolworths" if k % 2 == 0 else "coles", 9.99,
            size="unit unavailable", allow_duplicate=True, worksheet=ws)
    refused = (not res.get("wrote")) or res.get("error")
    refused_n += refused
    log_op("D", nm[:45], "exact_dup_add(allow_duplicate)", "both", "refused",
           f"wrote={res.get('wrote')} err={res.get('error')}", refused)
reorder_ok = 0
for k in range(0, 40, 2):
    nm = names[k]
    words = nm.split()
    reordered = " ".join([words[0], words[2], words[1], words[3]]) if len(words) == 4 else nm + " X"
    res = T(add_product_row, reordered, store_of_j[nm], 8.88, size="unit unavailable", worksheet=ws)
    same = res.get("merged") and res.get("row_index") == rowidx_by_name.get(nm)
    reorder_ok += same
    log_op("R", reordered[:45], "reorder_synth_add", store_of_j[nm],
           f"merge into row{rowidx_by_name.get(nm)}",
           f"wrote={res.get('wrote')} merged={res.get('merged')} row={res.get('row_index')}", same)
print(f"rule battery: merged {merged_n}/30, dup refused {refused_n}/10, reorder merge {reorder_ok}/20", flush=True)

# ---------------------------------------------------------- teardown
vals6 = T(ws.get_all_values)
synth_idxs = sorted((i for i, r in enumerate(vals6, start=1)
                     if r and r[0].strip().startswith("ZZT8")), reverse=True)
print(f"teardown: deleting {len(synth_idxs)} synth rows", flush=True)
if synth_idxs:
    T(ws.delete_rows, synth_idxs[0] - 1, synth_idxs[-1])   # 0-based half-open
vals7 = T(ws.get_all_values)
named = sum(1 for r in vals7[1:] if r and r[0].strip())
snap = json.loads(SNAP.read_text(encoding="utf-8"))
diff = sum(1 for s, c in zip(snap, vals7) for j in range(19)
           if (list(s) + [""] * 19)[j] != (list(c) + [""] * 19)[j])
print(f"named rows now: {named} | final drift vs snapshot: {diff}", flush=True)
for d in []:
    pass
summary = json.loads((LOGDIR / "t8_summary.json").read_text(encoding="utf-8")) if (LOGDIR / "t8_summary.json").exists() else {}
summary.update({
    "alias_verified": f"{ap}/{len(alias_targets)}",
    "kw_verified": f"{ak}/{len(kw_targets)}",
    "na_verified": f"{an}/{len(na_targets)}",
    "variant_merged": f"{merged_n}/30",
    "dup_refused": f"{refused_n}/10",
    "reorder_merge_ok": f"{reorder_ok}/20",
    "final_named_rows": named,
    "final_drift_cells": diff,
    "hard_failures": fails,
})
(LOGDIR / "t8_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print("FAILURES:", len(fails))
for f_ in fails[:30]:
    print("  -", f_)
print("DONE", flush=True)
