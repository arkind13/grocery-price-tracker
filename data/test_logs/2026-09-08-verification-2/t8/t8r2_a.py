"""T8 round-B2 driver, Phase A: 387 synthetic adds (D16/FIX-9 regression).

R2-11 LIVE EXERCISE: the grid is deliberately NOT pre-expanded (380 rows,
113 real). add_product_row's new grid-ceiling guard must expand it itself
when the append row would pass 380 — no raw APIError may escape.

Driver notes applied (retest-plan §7): store tracked in added-dict; bulk
verify with one get_all_values; numeric float compare; 1.3s gap on EVERY
ws call; 429 backoff x4.
"""
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker")
from core.sheets_client import connect_worksheet
from core.sheets_sync import add_product_row

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


ws = connect_worksheet()
print(f"grid at start: {ws.spreadsheet.fetch_sheet_metadata()}",
      flush=True) if False else None
sheet = T(ws.get_all_values)
real_rows = [r for r in sheet[1:] if r and r[0].strip()]
print(f"real rows: {len(real_rows)}", flush=True)

PRICE_COL = {"woolworths": 3, "coles": 4}  # 0-based: C=WW, D=Coles

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
added = {}   # name -> (row_index, store, j)  [driver note #1]
written = refused = 0
t0 = time.time()
for n in range(1, 388):
    nm = f"ZZT8R {n:04d} {GADGETS[n % len(GADGETS)]} {SIZES[(n // 7) % len(SIZES)]}"
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
        fails_line = f"add refused {nm}: wrote={res.get('wrote')} err={res.get('error')}"
        print(fails_line, flush=True)
        log_op(n, nm, "add", st, "wrote",
               f"wrote={res.get('wrote')} err={res.get('error')}", False)
    if n % 40 == 0:
        print(f"adds: {n}/387 (written={written} refused={refused}) "
              f"[{time.time()-t0:.0f}s]", flush=True)
print(f"PHASE A adds done: written={written} refused={refused}", flush=True)

# bulk verify (one read; numeric compare)
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
    if i != ri:
        log_op("A", nm, "row-mismatch", f"logged {ri}", f"found {i}", "", False)
    exp = round((j % 40) + 1.5, 2)
    got = vals[i - 1][PRICE_COL[st]] if len(vals[i - 1]) > PRICE_COL[st] else ""
    try:
        ok = abs(float(str(got).replace("$", "").strip()) - exp) < 0.005
    except (TypeError, ValueError):
        ok = False
    if not ok:
        log_op("A", nm, "price-verify", st, str(exp), repr(got), False)
ok_all = ph == 0 and written == len(added)
log_op("A", "PHASE-A bulk verify", "adds", "all",
       f"written==on-sheet=={len(added)}, 0 phantom",
       f"on-sheet={len(added) - ph} phantom={ph} written={written}", ok_all)
print(f"PHASE A verify: on-sheet={len(added)-ph} phantom={ph} written={written}",
      flush=True)

meta = ws.spreadsheet.fetch_sheet_metadata()
grid_rows = next(sh["properties"]["gridProperties"]["rowCount"]
                 for sh in meta["sheets"] if sh["properties"]["sheetId"] == ws.id)
print(f"grid rows after battery (fresh metadata): {grid_rows}", flush=True)
(LOGDIR / "phase_a_state.json").write_text(json.dumps({
    "written": written, "refused": refused, "phantom": ph,
    "added_names": synth_names, "added": {k: v for k, v in added.items()},
    "grid_rows_after": grid_rows, "real_rows": len(real_rows),
}, ensure_ascii=False, indent=1), encoding="utf-8")
print("PHASE A COMPLETE", flush=True)
