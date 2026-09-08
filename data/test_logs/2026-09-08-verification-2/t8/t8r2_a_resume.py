"""T8 round-B2 Phase A RESUME: adds 0035..0387 (0001-0034 survived the
quota-storm stop), then bulk-verify all 387. Same R2-11 live element: the
grid stays 380 rows; the guard must expand it itself at append row 381
(synth ~#267). GAP 2.0s, gentler 429 backoff.
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
GAP = 2.0
_last = [0.0]


def T(fn, *a, **k):
    gap = time.time() - _last[0]
    if gap < GAP:
        time.sleep(GAP - gap)
    for attempt in range(5):
        try:
            r = fn(*a, **k)
            _last[0] = time.time()
            return r
        except Exception as e:
            if "429" in str(e) and attempt < 4:
                wait = 75 * (attempt + 1)
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


GADGETS = ["Sparkling Water", "Rice Crackers", "Dish Soap", "Almond Milk",
           "Turmeric Powder", "Green Tea", "Pasta Sauce", "Rye Bread",
           "Olive Oil", "Chickpeas", "Basmati Rice", "Salty Crackers",
           "Coconut Yoghurt", "Butter Beans", "Tomato Paste", "Maple Syrup",
           "Peanut Butter", "Corn Flakes", "Paper Towel", "Dish Sponges",
           "Vanilla Ice Cream", "Salted Cashews", "Muesli Bars",
           "Long Life Milk", "Black Coffee"]
SIZES = ["250g", "500g", "1kg", "2L", "750mL", "12 Pack", "5 Pack",
         "300g", "150g", "4 Pack"]


def mk(n):
    return (f"ZZT8R {n:04d} {GADGETS[n % len(GADGETS)]} "
            f"{SIZES[(n // 7) % len(SIZES)]}")


ws = connect_worksheet()
sheet = T(ws.get_all_values)
real_n = sum(1 for r in sheet[1:] if r and r[0].strip())
print(f"real rows: {real_n - 34} + 34 synth already on sheet", flush=True)

PRICE_COL = {"woolworths": 3, "coles": 4}
added = {}
for i, r in enumerate(sheet, start=1):
    if r and r[0].strip().startswith("ZZT8R"):
        nm = r[0].strip()
        n = int(nm.split()[1])
        j = n - 1
        st = "woolworths" if j % 2 == 0 else "coles"
        added[nm] = (i, st, j)
print(f"pre-existing synth recovered: {len(added)}", flush=True)

written = refused = 0
t0 = time.time()
for n in range(35, 388):
    nm = mk(n)
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
        print(f"add refused {nm}: wrote={res.get('wrote')} err={res.get('error')}",
              flush=True)
        log_op(n, nm, "add", st, "wrote",
               f"wrote={res.get('wrote')} err={res.get('error')}", False)
    if n % 40 == 0:
        print(f"adds: {n}/387 (written={written} refused={refused}) "
              f"[{time.time()-t0:.0f}s]", flush=True)
print(f"PHASE A adds done: new={written} refused={refused} total={len(added)}",
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
ok_all = ph == 0 and len(added) == 387
log_op("A", "PHASE-A bulk verify", "adds", "all",
       "written==on-sheet==387, 0 phantom",
       f"on-sheet={len(added) - ph} phantom={ph} total={len(added)}", ok_all)
print(f"PHASE A verify: on-sheet={len(added)-ph} phantom={ph} total={len(added)}",
      flush=True)

meta = ws.spreadsheet.fetch_sheet_metadata()
grid_rows = next(sh["properties"]["gridProperties"]["rowCount"]
                 for sh in meta["sheets"] if sh["properties"]["sheetId"] == ws.id)
print(f"grid rows after battery (fresh metadata): {grid_rows}", flush=True)
synth_names = sorted(added, key=lambda n: int(n.split()[1]))
(LOGDIR / "phase_a_state.json").write_text(json.dumps({
    "written": written + 34, "refused": refused, "phantom": ph,
    "added_names": synth_names,
    "added": {k: list(v) for k, v in added.items()},
    "grid_rows_after": grid_rows, "real_rows": real_n - 34,
    "note": "resumed after quota-storm stop; 34 rows pre-existed and were "
            "recovered from the sheet (each passed add_product_row's "
            "in-call read-back verify when originally written)",
}, ensure_ascii=False, indent=1), encoding="utf-8")
print("PHASE A COMPLETE", flush=True)
