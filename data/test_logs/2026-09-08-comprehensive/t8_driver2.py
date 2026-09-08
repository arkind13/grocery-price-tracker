"""T8 v2 — 500-item battery, quota-safe (throttled writes + 429 backoff).

Same coverage as v1: 113 real items (lookup + price update + revert),
387 synthetic items (add, price update, alias/keyword/NA subsets,
GONE->resurrection), one-line-rule variants, exact-dup refusals,
reorder merges, batch verify, teardown + full-grid drift check.
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
                              _append_alias, _find_col)
from core.lookup import LookupIndex

LOGDIR = Path(r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker\data\test_logs\2026-09-08-comprehensive")
OPS = LOGDIR / "t8_ops_log.csv"
SNAP = LOGDIR / "baselines" / "t8_sheet_snapshot.json"

rng = random.Random(20260908)
ws = connect_worksheet()

_last_write = [0.0]
WRITE_MIN_GAP = 1.25


def W(fn, *a, **k):
    """Throttled write with 429 backoff."""
    gap = time.time() - _last_write[0]
    if gap < WRITE_MIN_GAP:
        time.sleep(WRITE_MIN_GAP - gap)
    for attempt in range(4):
        try:
            r = fn(*a, **k)
            _last_write[0] = time.time()
            return r
        except Exception as e:
            if "429" in str(e) and attempt < 3:
                wait = 40 * (attempt + 1)
                print(f"[429] backing off {wait}s", flush=True)
                time.sleep(wait)
            else:
                raise


def log_op(item_no, name, op, target, expected, actual, ok):
    with OPS.open("a", encoding="utf-8") as f:
        w = csv.writer(f)
        if f.tell() == 0:
            w.writerow(["ts", "item_no", "item", "op", "target", "expected", "actual", "pass"])
        w.writerow([datetime.now().strftime("%H:%M:%S"), item_no, name[:60], op,
                    target, str(expected)[:70], str(actual)[:70], "PASS" if ok else "FAIL"])


fails: list[str] = []


def note_fail(msg):
    fails.append(msg)
    print("FAIL:", msg, flush=True)


# ---------------------------------------------------------------- pool
sheet = ws.get_all_values()
header, rows = sheet[0], sheet[1:]
real_items = [(i, r[0].strip()) for i, r in enumerate(rows, start=2)
              if len(r) > 0 and r[0].strip()]
assert len(real_items) == 113, f"expected 113 real rows, got {len(real_items)}"

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
    synth_names.append(f"ZZT8 {n:04d} {GADGETS[n % len(GADGETS)]} {SIZES[(n // 7) % len(SIZES)]}")

store_of = lambda k: "woolworths" if k % 2 == 0 else "coles"
other = {"woolworths": "coles", "coles": "woolworths"}
PRICE_COL = {"woolworths": 3, "coles": 4}       # 0-based sheet index
orig_row_by_name = {r[0].strip(): (i, r) for i, r in enumerate(rows, start=2)}

# ========================================================== PHASE 1 — real items
print(f"=== PHASE 1: {len(real_items)} real items (exact-index + update + revert) ===", flush=True)
idx = LookupIndex(rows, header)
p1_start = time.time()
for k, (row_i, nm) in enumerate(real_items):
    hit = idx.find_exact(nm)
    log_op(k + 1, nm, "exact_index_lookup", f"row{row_i}",
           "found", f"hit={'yes' if hit else 'no'}", bool(hit))
    orig = orig_row_by_name[nm][1]
    st = store_of(k)
    pcol = PRICE_COL[st]
    new_price = round((abs(hash(nm)) % 4000) / 100 + 1.0, 2)
    r = W(update_single_price, nm, st, new_price, worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op(k + 1, nm, f"update_price:{st}", f"row{r.get('row_index')}", f"wrote {new_price}",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)
    if not ok:
        note_fail(f"real#{k+1} update {nm}: {r}")
    # verify cell then revert raw
    a1 = f"{chr(ord('A')+pcol)}{r.get('row_index')}"
    got = ws.get(a1)
    got_v = got[0][0] if got and got[0] else ""
    log_op(k + 1, nm, "verify_price_write", a1, str(new_price), got_v, got_v == str(new_price))
    W(ws.update, values=[[orig[pcol] if len(orig) > pcol else ""]], range_name=a1)
    log_op(k + 1, nm, "revert_price", a1, orig[pcol], "written", True)
print(f"phase1 done in {round(time.time()-p1_start,1)}s", flush=True)

# ========================================================== PHASE 2 — synthetic
print(f"=== PHASE 2: {len(synth_names)} synthetic items ===", flush=True)
added = {}
p2_start = time.time()
for j, nm in enumerate(synth_names):
    no = 114 + j
    st = store_of(j)
    price = round((j % 40) + 1.5, 2)
    use_kw = (j % 8 == 0)
    use_alias = (j % 7 == 0)
    try:
        r = W(add_product_row, nm, st, price, size=SIZES[(j // 7) % len(SIZES)],
              store_keyword=(f"{nm} — STORE NAME" if use_kw else ""),
              alias=("zzt8 query " + str(j) if use_alias else ""),
              worksheet=ws)
        wrote = r.get("wrote") and not r.get("error")
        log_op(no, nm, "add_row", st, "new row",
               f"wrote={r.get('wrote')} row={r.get('row_index')} merged={r.get('merged')} err={r.get('error')}", wrote)
        if wrote and r.get("row_index"):
            added[nm] = r["row_index"]
        else:
            note_fail(f"synth#{no} add {nm}: {r}")
    except Exception as e:
        note_fail(f"synth#{no} add EXC {nm}: {type(e).__name__}: {e}")
print(f"phase2 adds done ({len(added)}) in {round(time.time()-p2_start,1)}s", flush=True)

names_with_rows = list(added.items())
p2b = time.time()
for k, (nm, _ri) in enumerate(names_with_rows):
    no = 114 + k
    st = other[store_of(k)]
    newp = round((k % 30) + 2.25, 2)
    r = W(update_single_price, nm, st, newp, worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op(no, nm, f"update_price:{st}", f"row{r.get('row_index')}", f"wrote {newp}",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)
    if not ok:
        note_fail(f"synth#{no} update {nm}: {r}")
print(f"phase2 price updates done in {round(time.time()-p2b,1)}s", flush=True)

# chunk verify every 40 adds
vals = ws.get_all_values()
val_by_row = {i: r for i, r in enumerate(vals, start=1)}
vp = vf = 0
for k, (nm, rowidx) in enumerate(names_with_rows):
    r_ = val_by_row.get(rowidx, [])
    name_ok = len(r_) > 0 and r_[0].strip() == nm
    unit_ok = len(r_) > 2 and r_[2].strip() == SIZES[(k // 7) % len(SIZES)]
    st = store_of(k)
    p_ok = len(r_) > PRICE_COL[st] and r_[PRICE_COL[st]].strip() != ""
    o_ok = len(r_) > PRICE_COL[other[st]] and r_[PRICE_COL[other[st]]].strip() != ""
    ok = name_ok and unit_ok and p_ok and o_ok
    vp += ok
    vf += (not ok)
    if not ok:
        note_fail(f"synth#{114+k} verify {nm}: name={name_ok} unit={unit_ok} p={p_ok} o={o_ok} row={rowidx}")
print(f"synth verify: pass={vp} fail={vf}", flush=True)

# subsets (single pass, throttled)
colA_now = ws.col_values(1)
def row_of(nm):
    return next((i for i, v in enumerate(colA_now, start=1) if v.strip() == nm), None)

p_alias = names_with_rows[3::8][:50]
p_kw = names_with_rows[5::8][:50]
p_na = names_with_rows[2::6][:60]
p_gone = names_with_rows[4::20][:19]

kw_p_col = chr(ord("A") + _find_col(header, "Keywords"))
for nm, _ri in p_alias:
    i = row_of(nm)
    if not i:
        note_fail(f"alias target missing {nm}"); continue
    before = ws.get(f"{kw_p_col}{i}")
    out = W(_append_alias, ws, header, i, "zzt8 extra alias")
    after = ws.get(f"{kw_p_col}{i}")
    ok = (after != before)
    log_op("alias", nm, "append_alias", f"{kw_p_col}{i}", "appended", str(ok), ok)

for nm, _ri in p_kw:
    i = row_of(nm)
    if not i:
        note_fail(f"kw target missing {nm}"); continue
    st = store_of(i - 2)
    r = W(set_store_keyword, nm, st, f"ZZT8 STORE KEYWORD for {nm}", worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op("kw", nm, f"set_keyword:{st}", f"row{r.get('row_index')}", "wrote",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)

for nm, _ri in p_na:
    i = row_of(nm)
    if not i:
        note_fail(f"na target missing {nm}"); continue
    st = store_of(i - 2)
    r = W(mark_not_available, nm, st, worksheet=ws)
    ok = r.get("wrote") and not r.get("error")
    log_op("na", nm, f"mark_na:{st}", f"row{r.get('row_index')}", "NA written",
           f"wrote={r.get('wrote')} err={r.get('error')}", ok)

for nm, _ri in p_gone:
    i = row_of(nm)
    if not i:
        note_fail(f"gone target missing {nm}"); continue
    st = store_of(i - 2)
    a1 = f"{chr(ord('A')+PRICE_COL[st])}{i}"
    W(ws.update, values=[["GONE"]], range_name=a1)
    back = ws.get(a1)
    back_v = back[0][0] if back and back[0] else ""
    log_op("gone", nm, "stamp_gone", a1, "GONE", back_v, back_v == "GONE")
    r = W(update_single_price, nm, st, 7.77, worksheet=ws)
    back2 = ws.get(a1)
    back2_v = back2[0][0] if back2 and back2[0] else ""
    ok = r.get("wrote") and back2_v != "GONE"
    log_op("gone", nm, "resurrect_via_update", a1, "cleared", back2_v, ok)
    if not ok:
        note_fail(f"gone/resurrect {nm}: wrote={r.get('wrote')} cell={back2_v}")

# ========================================================== PHASE 3 — one-line rule
print("=== PHASE 3: variant/dup battery ===", flush=True)
for k, (row_i, nm) in enumerate(real_items[:30]):
    words = nm.split()
    variant = (" ".join([words[-1]] + words[:-1]) if k % 2 == 0 and len(words) > 1
               else nm.lower())
    orig = orig_row_by_name[nm][1]
    r = W(add_product_row, variant, store_of(k), 9.99, size="unit unavailable", worksheet=ws)
    if r.get("merged"):
        prow = r.get("row_index")
        pcol = PRICE_COL[store_of(k)]
        W(ws.update, values=[[orig[pcol] if len(orig) > pcol else ""]], range_name=f"{chr(ord('A')+pcol)}{prow}")
        W(ws.update, values=[[orig[15] if len(orig) > 15 else ""]], range_name=f"P{prow}")
        log_op("V", variant[:45], f"variant_add(merged row{prow}, reverted)", store_of(k),
               "merged", f"wrote={r.get('wrote')} merged={r.get('merged')}", True)
    else:
        newrow = r.get("row_index")
        if r.get("wrote") and newrow:
            pass  # will be caught in teardown sweep below
        log_op("V", variant[:45], f"variant_add(row{newrow})", store_of(k),
               "EXPECTED merge", f"wrote={r.get('wrote')} merged={r.get('merged')}", r.get("merged"))
        if r.get("wrote") and newrow:
            note_fail(f"variant DID NOT merge: {variant!r} created row {newrow}")

dup_refused = 0
for k, (row_i, nm) in enumerate(real_items[:10]):
    r = W(add_product_row, nm, store_of(k), 9.99, size="unit unavailable",
          allow_duplicate=True, worksheet=ws)
    refused = (not r.get("wrote")) or r.get("error")
    dup_refused += refused
    log_op("D", nm[:45], "exact_dup_add(allow_duplicate)", store_of(k),
           "refused", f"wrote={r.get('wrote')} err={r.get('error')}", refused)

reorder_ok = 0
for k in range(0, 40, 2):
    nm = synth_names[k]
    words = nm.split()
    reordered = " ".join([words[0], words[2], words[1], words[3]]) if len(words) == 4 else nm + " X"
    r = W(add_product_row, reordered, store_of(k), 8.88, size="unit unavailable", worksheet=ws)
    same = r.get("merged") and r.get("row_index") == added.get(nm)
    reorder_ok += same
    log_op("R", reordered[:45], "reorder_synth_add", store_of(k),
           f"merge into row{added.get(nm)}", f"wrote={r.get('wrote')} merged={r.get('merged')} row={r.get('row_index')}", same)
print(f"phase3 done: dup_refused={dup_refused}/10 reorder_merge_ok={reorder_ok}/20", flush=True)

# ========================================================== PHASE 4 — teardown
print("=== PHASE 4: teardown ===", flush=True)
vals4 = ws.get_all_values()
synth_row_idxs = sorted((i for i, r in enumerate(vals4, start=1)
                         if len(r) > 0 and r[0].strip().startswith("ZZT8")), reverse=True)
print(f"synth rows to delete: {len(synth_row_idxs)}", flush=True)
contig = (synth_row_idxs and
          all(synth_row_idxs[i] - synth_row_idxs[i + 1] == 1 for i in range(len(synth_row_idxs) - 1)))
if contig and synth_row_idxs:
    W(ws.delete_rows, synth_row_idxs[-1], synth_row_idxs[0])
    print(f"deleted contiguous block {synth_row_idxs[-1]}..{synth_row_idxs[0]} in ONE call", flush=True)
else:
    for ri in synth_row_idxs:
        W(ws.delete_rows, ri)

# revert any variant-merge price leakage (final grid restore from snapshot would
# also do it, but per-cell keeps the audit trail)
vals5 = ws.get_all_values()
names_now = [r[0].strip() for r in vals5[1:] if len(r) > 0 and r[0].strip()]
leftover = [x for x in names_now if x.startswith("ZZT8")]
print(f"leftover synth rows: {len(leftover)}; named rows now: {len(names_now)}", flush=True)

# full-grid drift check vs snapshot
snap = json.loads(SNAP.read_text(encoding="utf-8"))
drift = []
for i in range(max(len(snap), len(vals5))):
    srow = list(snap[i]) + [""] * 19 if i < len(snap) else []
    crow = list(vals5[i]) + [""] * 19 if i < len(vals5) else []
    for j in range(19):
        if (srow[j] if srow else "") != (crow[j] if crow else ""):
            drift.append(f"row{i+1} col{j+1}: {(srow[j] if srow else '')!r} -> {(crow[j] if crow else '')!r}")
for d in drift[:60]:
    print("DRIFT:", d, flush=True)

summary = {
    "items_total": 500,
    "real_items": 113,
    "synth_items": 387,
    "synth_verify_pass": vp,
    "synth_verify_fail": vf,
    "dup_refused": dup_refused,
    "reorder_merge_ok": reorder_ok,
    "leftover_synth_rows": len(leftover),
    "final_drift_cells": len(drift),
    "drift": drift,
    "hard_failures": fails,
}
(LOGDIR / "t8_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
print("SUMMARY:", json.dumps({k: v for k, v in summary.items()
                              if k not in ("drift", "hard_failures")}, indent=1), flush=True)
print("FAILURES:", len(fails), flush=True)
