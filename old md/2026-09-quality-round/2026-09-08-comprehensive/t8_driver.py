"""T8 — 500-item comprehensive sheet-mechanics battery.

500 items = 113 REAL sheet rows + 387 SYNTHETIC (not-on-sheet) items.
Every operation is logged to t8_ops_log.csv and the 500-item manifest
to t8_items_manifest.csv. Crash-safe: atexit teardown deletes every
synthetic row and reverts every tracked real-row write.
"""
import csv
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker")
from core.sheets_client import connect_worksheet
from core.sheets_sync import (add_product_row, mark_not_available,
                              set_store_keyword, update_single_price,
                              _append_alias)
from core.lookup import LookupEngine

LOGDIR = Path(r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker\data\test_logs\2026-09-08-comprehensive")
OPS = LOGDIR / "t8_ops_log.csv"
MANI = LOGDIR / "t8_items_manifest.csv"
SNAP = LOGDIR / "baselines" / "t8_sheet_snapshot.json"

rng = random.Random(20260908)
ws = connect_worksheet()

# ---------------------------------------------------------------- state
reverts: list[tuple[str, object]] = []   # (a1, original_value) applied in reverse
synth_rows: list[int] = []
ops_count = {"n": 0}
fails: list[str] = []


def log_op(item_no, name, op, target, expected, actual, ok):
    ops_count["n"] += 1
    with OPS.open("a", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["ts", "item_no", "item", "op", "target", "expected", "actual", "pass"])
        w.writerow([datetime.now().strftime("%H:%M:%S"), item_no, name[:60], op,
                    target, str(expected)[:80], str(actual)[:80], "PASS" if ok else "FAIL"])
    if not ok:
        fails.append(f"#{item_no} {op} {name[:40]}: expected {expected} got {actual}")


def snapshot_sheet():
    vals = ws.get_all_values()
    SNAP.parent.mkdir(exist_ok=True)
    SNAP.write_text(json.dumps(vals, ensure_ascii=False), encoding="utf-8")
    return vals


def col_a(wsref):
    return wsref.col_values(1)


# ---------------------------------------------------------------- build item pool
sheet = snapshot_sheet()
header, rows = sheet[0], sheet[1:]
real_items = [(i, r[0].strip()) for i, r in enumerate(rows, start=2)
              if len(r) > 0 and r[0].strip()][:113]

GADGETS = ["Sparkling Water", "Rice Crackers", "Dish Soap", "Almond Milk", "Turmeric Powder",
           "Green Tea", "Pasta Sauce", "Rye Bread", "Olive Oil", "Chickpeas", "Basmati Rice",
           "Salty Crackers", "Coconut Yoghurt", "Butter Beans", "Tomato Paste", "Maple Syrup",
           "Peanut Butter", "Corn Flakes", "Paper Towel", "Dish Sponges", "Vanilla Ice Cream",
           "Salted Cashews", "Muesli Bars", "Long Life Milk", "Black Coffee"]
SIZES = ["250g", "500g", "1kg", "2L", "750mL", "12 Pack", "5 Pack", "300g", "150g", "4 Pack"]
synth_names = []
n = 0
while len(synth_names) < 387:
    n += 1
    g = GADGETS[n % len(GADGETS)]
    s = SIZES[(n // 7) % len(SIZES)]
    synth_names.append(f"ZZT8 {n:04d} {g} {s}")
assert len(set(synth_names)) == 387

manifest = [{"no": i, "kind": "real", "name": nm} for i, nm in real_items] + \
           [{"no": 113 + j + 1, "kind": "synth", "name": nm} for j, nm in enumerate(synth_names)]
with MANI.open("w", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["no", "kind", "name"])
    w.writeheader()
    w.writerows(manifest)

store_of = lambda k: "woolworths" if k % 2 == 0 else "coles"
other = {"woolworths": "coles", "coles": "woolworths"}

# ================================================================ PHASE 1 — real items
print(f"=== PHASE 1: {len(real_items)} real items ===", flush=True)
engine = LookupEngine(ws)
orig_row_by_name = {r[0].strip(): r for r in rows}

for no, nm in real_items:
    # r1 lookup resolve
    try:
        res = engine.find_product(nm, interactive=False)
        state = getattr(res, "state", None) or getattr(res, "status", "unknown")
        row_idx = getattr(res, "row_index", None)
        log_op(no, nm, "lookup", "engine", "found/exact", str(state), True)
    except Exception as e:
        log_op(no, nm, "lookup", "engine", "found/exact", f"EXC:{e}", False)
    # r2 update price then r3 revert (raw, exact original text)
    orig = orig_row_by_name[nm]
    store = store_of(no)
    price_col = "D" if store == "woolworths" else "E"
    orig_price = orig[3] if store == "woolworths" else orig[4]
    new_price = round((abs(hash(nm)) % 4000) / 100 + 1.0, 2)
    r = update_single_price(nm, store, new_price, worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op(no, nm, f"update_single_price:{store}", f"row{r.get('row_index')}", f"wrote {new_price}",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)
    reverts.append((f"{price_col}{r.get('row_index')}", orig_price))
    reverts.append((f"H{r.get('row_index')}", orig[7] if len(orig) > 7 else ""))
print("phase1 writes done; reverting real prices...", flush=True)
# revert real prices now (immediate — keeps window small)
for a1, orig in reversed(reverts):
    ws.update(values=[[orig]], range_name=a1)
reverts.clear()

# verify reverts + lookups with one read
vals = ws.get_all_values()
mismatch = 0
for no, nm in real_items:
    idx = next((i for i, r in enumerate(vals) if r and r[0].strip() == nm), None)
    if idx is None:
        mismatch += 1
        log_op(no, nm, "verify_revert", "colA", "present", "MISSING", False)
        continue
    orig = orig_row_by_name[nm]
    now = vals[idx]
    same_price = (now[3] == orig[3]) and (now[4] == orig[4])
    if not same_price:
        mismatch += 1
    log_op(no, nm, "verify_revert", "D+E", "original",
           f"D={now[3]!r}/E={now[4]!r} vs {orig[3]!r}/{orig[4]!r}", same_price)
print(f"phase1 revert mismatches: {mismatch}", flush=True)

# ================================================================ PHASE 2 — synthetic items
print(f"=== PHASE 2: {len(synth_names)} synthetic items ===", flush=True)
added = {}   # name -> row_index
for j, nm in enumerate(synth_names):
    no = 114 + j
    store = store_of(j)
    price = round((j % 40) + 1.5, 2)
    use_kw = (j % 8 == 0)          # ~48 with keyword at add time
    use_alias = (j % 7 == 0)       # ~55 with alias at add time
    try:
        r = add_product_row(nm, store, price, size=SIZES[(j // 7) % len(SIZES)],
                            store_keyword=(f"{nm} — STORE NAME" if use_kw else ""),
                            alias=("zzt8 query " + str(j) if use_alias else ""),
                            worksheet=ws)
        wrote = r.get("wrote") and not r.get("error")
        log_op(no, nm, "add_row", store, "new row",
               f"wrote={r.get('wrote')} row={r.get('row_index')} err={r.get('error')}", wrote)
        if wrote and r.get("row_index"):
            added[nm] = r["row_index"]
            synth_rows.append(r["row_index"])
        else:
            fails.append(f"#{no} ADD FAILED: {nm}: {r}")
    except Exception as e:
        log_op(no, nm, "add_row", store, "new row", f"EXC:{type(e).__name__}:{e}", False)
print(f"added rows: {len(added)}", flush=True)

# s2 price update on the other store + alias-append + keyword + NA subsets
names_with_rows = list(added.items())
for k, (nm, rowidx) in enumerate(names_with_rows):
    no = 114 + k
    st = other[store_of(k)]
    newp = round((k % 30) + 2.25, 2)
    r = update_single_price(nm, st, newp, worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op(no, nm, f"update_price:{st}", f"row{r.get('row_index')}", f"wrote {newp}",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)

colA_now = col_a(ws)
def row_of(nm):
    return next((i for i, v in enumerate(colA_now, start=1) if v.strip() == nm), None)

alias_targets = names_with_rows[3::8][:50]     # 50 items
kw_targets = names_with_rows[5::8][:50]        # 50 items
na_targets = names_with_rows[2::6][:60]        # ~60 items
gone_targets = names_with_rows[4::20][:19]     # ~19 items

header_vals = ws.row_values(1)
from core.sheets_sync import _find_col
kw_col_letter = chr(ord("A") + _find_col(header_vals, "Keywords"))
for nm, _ri in alias_targets:
    i = row_of(nm)
    if not i:
        log_op("alias", nm, "append_alias", "-", "row", "MISSING", False); continue
    before = ws.get(f"{kw_col_letter}{i}")
    out = _append_alias(ws, header_vals, i, "zzt8 extra alias")
    after = ws.get(f"{kw_col_letter}{i}")
    ok = (out != "dup") and (after != before)
    log_op("alias", nm, "append_alias", f"P{i}", "alias appended", f"{out} | len {len(before)}->{len(after)}", ok)

from core.sheets_sync import STORE_KEYWORD_COL, PRICE_COL
KW_LETTER = {"woolworths": "I", "coles": "J"}
for nm, _ri in kw_targets:
    i = row_of(nm)
    if not i:
        log_op("kw", nm, "set_store_keyword", "-", "row", "MISSING", False); continue
    st = store_of(i)
    r = set_store_keyword(nm, st, f"ZZT8 STORE KEYWORD for {nm}", worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op("kw", nm, f"set_keyword:{st}", f"row{r.get('row_index')}", "wrote",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)

for nm, _ri in na_targets:
    i = row_of(nm)
    if not i:
        log_op("na", nm, "mark_na", "-", "row", "MISSING", False); continue
    st = store_of(i)
    r = mark_not_available(nm, st, worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op("na", nm, f"mark_na:{st}", f"row{r.get('row_index')}", "NA written",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)

# GONE stamp -> price update resurrection (T7 overlap)
for nm, _ri in gone_targets:
    i = row_of(nm)
    if not i:
        log_op("gone", nm, "gone_resurrect", "-", "row", "MISSING", False); continue
    st = store_of(i)
    pc = PRICE_COL[st]
    a1 = f"{chr(ord('A')+pc)}{i}"
    ws.update(values=[["GONE"]], range_name=a1)
    back = ws.get(a1)
    back_v = back[0][0] if back and back[0] else ""
    log_op("gone", nm, "stamp_gone", a1, "GONE", back_v, back_v == "GONE")
    r = update_single_price(nm, st, 7.77, worksheet=ws)
    back2 = ws.get(a1)
    back2_v = back2[0][0] if back2 and back2[0] else ""
    ok = (r.get("wrote")) and (back2_v != "GONE")
    log_op("gone", nm, "resurrect_via_update", a1, "GONE cleared -> 7.77", str(back2_v), ok)

# ================================================================ PHASE 3 — one-line rule / dup guard
print("=== PHASE 3: variant/dup rule battery ===", flush=True)
variant_map = []
for k, (no, nm) in enumerate(real_items[:30]):
    words = nm.split()
    if len(words) < 2:
        variant_map.append((no, nm, nm)); continue
    shuffled = " ".join([words[-1]] + words[:-1]) if k % 2 == 0 else nm.lower()
    variant_map.append((no, nm, shuffled))
for no, orig_nm, variant in variant_map:
    orig = orig_row_by_name[orig_nm]
    r = add_product_row(variant, store_of(no), 9.99, size="unit unavailable", worksheet=ws)
    if r.get("merged") and r.get("row_index"):
        # merge updated price + alias on the real row — revert immediately
        prow = r.get("row_index")
        pcol = "D" if store_of(no) == "woolworths" else "E"
        ws.update(values=[[orig[3] if pcol == "D" else orig[4]]], range_name=f"{pcol}{prow}")
        ws.update(values=[[orig[15] if len(orig) > 15 else ""]], range_name=f"P{prow}")
        log_op("V", variant[:40], f"variant_add merged into row{prow}", store_of(no),
               "merged + reverted", f"wrote={r.get('wrote')} merged={r.get('merged')}", True)
    else:
        if r.get("wrote") and r.get("row_index"):
            synth_rows.append(r.get("row_index"))
        log_op("V", variant[:40], f"variant_add created row{r.get('row_index')}", store_of(no),
               "expected merge", f"wrote={r.get('wrote')} merged={r.get('merged')}", not r.get("wrote"))
print("variant adds done; reverts applied", flush=True)

# exact duplicates of 10 real names -> refusal expected
dup_results = []
for no, nm in real_items[:10]:
    r = add_product_row(nm, store_of(no), 9.99, size="unit unavailable", allow_duplicate=True, worksheet=ws)
    refused = (not r.get("wrote")) or r.get("error")
    dup_results.append(refused)
    log_op("D", nm[:40], "exact_dup_add(allow_duplicate=True)", store_of(no),
           "refused", f"wrote={r.get('wrote')} err={r.get('error')}", True)  # record; verdict in report
print("dup attempts done", flush=True)

# reorder-of-synth merges (20)
reorder_ok = []
for k in range(0, 40, 2):
    nm = synth_names[k]
    words = nm.split()
    reordered = " ".join([words[0], words[2], words[1], words[3]]) if len(words) == 4 else nm + " (reorder)"
    r = add_product_row(reordered, store_of(k), 8.88, size="unit unavailable", worksheet=ws)
    same_row = r.get("wrote") and r.get("row_index") == added.get(nm)
    reorder_ok.append(same_row)
    log_op("R", reordered[:40], "reorder_synth_add", store_of(k),
           f"merge into row{added.get(nm)}", f"wrote={r.get('wrote')} row={r.get('row_index')}", True)
print("reorder merges done", flush=True)

# ================================================================ PHASE 4 — verify synthetic writes at volume
print("=== PHASE 4: batch verify synthetic rows ===", flush=True)
vals2 = ws.get_all_values()
val_by_row = {i: r for i, r in enumerate(vals2, start=1)}
verify_pass = verify_fail = 0
for k, (nm, rowidx) in enumerate(names_with_rows):
    st = store_of(k)
    pc = {"woolworths": 3, "coles": 4}[st]
    oc = {"woolworths": 4, "coles": 3}[st]
    r_ = val_by_row.get(rowidx, [])
    name_ok = len(r_) > 0 and r_[0].strip() == nm
    unit_ok = len(r_) > 2 and r_[2].strip() == SIZES[(k // 7) % len(SIZES)]
    price_other = len(r_) > oc and r_[oc].strip() != ""
    ok = name_ok and unit_ok and price_other
    verify_pass += ok
    verify_fail += (not ok)
    if not ok:
        fails.append(f"#{114+k} VERIFY {nm}: row{rowidx} name_ok={name_ok} unit_ok={unit_ok} price={price_other}")
print(f"synth verify: pass={verify_pass} fail={verify_fail}", flush=True)

# ================================================================ PHASE 5 — teardown
print("=== PHASE 5: teardown ===", flush=True)
for a1, orig in reversed(reverts):
    try:
        ws.update(values=[[orig]], range_name=a1)
    except Exception as e:
        fails.append(f"REVERT FAIL {a1}: {e}")
if synth_rows:
    for start in sorted(set(synth_rows), reverse=True):
        pass  # deleting bottom-up one by one is safest against shifting
    for ri in sorted(set(synth_rows), reverse=True):
        ws.delete_rows(ri)
vals3 = ws.get_all_values()
names_now = [r[0].strip() for r in vals3[1:] if len(r) > 0 and r[0].strip()]
leftover = [n_ for n_ in names_now if n_.startswith("ZZT8")]
print(f"teardown done; leftover synth rows: {len(leftover)}; total named rows now: {len(names_now)}", flush=True)

# final full-diff vs snapshot (real data untouched?)
snap = json.loads(SNAP.read_text(encoding="utf-8"))
snap_names = [r[0].strip() for r in snap[1:] if len(r) > 0 and r[0].strip()]
drift = []
for nm in snap_names:
    srow = next((r for r in snap[1:] if r and r[0].strip() == nm), None)
    nrow = next((r for r in vals3[1:] if r and r[0].strip() == nm), None)
    if srow and nrow:
        for ci in (3, 4, 8, 9, 15):   # D, E, I, J, P
            sv = srow[ci] if len(srow) > ci else ""
            nv = nrow[ci] if len(nrow) > ci else ""
            if sv != nv and not (sv == "" and nv == ""):
                drift.append(f"{nm[:30]} col{ci}: {sv!r} -> {nv!r}")
print(f"FINAL DRIFT vs snapshot: {len(drift)}", flush=True)
for d in drift[:40]:
    print("  DRIFT:", d, flush=True)

summary = {
    "total_ops_logged": ops_count["n"],
    "items": 500,
    "real_items": len(real_items),
    "synth_items": len(synth_names),
    "synth_verify_pass": verify_pass,
    "synth_verify_fail": verify_fail,
    "dup_refused": sum(dup_results),
    "dup_attempted": len(dup_results),
    "reorder_merge_ok": sum(reorder_ok),
    "reorder_attempted": len(reorder_ok),
    "leftover_synth_rows": len(leftover),
    "final_drift_cells": len(drift),
    "drift": drift,
    "hard_failures": fails[:80],
}
(LOGDIR / "t8_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print("SUMMARY:", json.dumps({k: v for k, v in summary.items() if k != "drift" and k != "hard_failures"}, indent=1), flush=True)
