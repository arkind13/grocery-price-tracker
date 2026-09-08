"""Check 1c (R3-1 live accept, reduced): modest bulk add of 25 synthetic
rows through add_product_row (the guard-bearing path) against the REAL
sheet. Pass = zero raw APIError, every add written + read-back verified,
teardown removes all 25 (inclusive delete_rows), 113 named rows and grid
380 restored. Single writer, >=1.3s throttle between writes.
"""
import csv
import json
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\User.DESKTOP-R2G441H\Documents\AI related\grocery-price-tracker")
sys.path.insert(0, str(REPO))
from core.sheets_client import connect_worksheet  # noqa: E402
from core import sheets_sync  # noqa: E402

PREFIX = "ZZV3B3 Guard Probe"
N = 25
OUT = Path(__file__).parent
THROTTLE = 1.4

ws = connect_worksheet()
grid_before = sheets_sync._worksheet_grid_rows(ws)
vals = ws.get_all_values()
named_before = sum(1 for r in vals[1:] if r and r[0].strip())
print(f"pre: grid={grid_before} named={named_before}")
assert named_before == 113, f"expected 113 named rows before battery, got {named_before}"

ops = []
raw_api_errors = 0
written = 0
t0 = time.time()
for i in range(1, N + 1):
    name = f"{PREFIX} {i:02d}"
    try:
        res = sheets_sync.add_product_row(
            name, "woolworths", round(1.0 + i * 0.01, 2),
            size="1ea", category="zz-probe", dry_run=False)
    except Exception as exc:
        raw_api_errors += 1
        ops.append({"i": i, "name": name, "error": repr(exc)[:200],
                    "raw_apierror": "APIError" in repr(exc)})
        print(f"add {i:02d}: EXCEPTION {exc!r}")
        if raw_api_errors > 3:
            print("aborting: too many exceptions")
            break
        time.sleep(THROTTLE)
        continue
    ok = bool(res.get("wrote")) and not res.get("error")
    if isinstance(res.get("error"), str) and "APIError" in res["error"]:
        raw_api_errors += 1
    written += 1 if ok else 0
    ops.append({"i": i, "name": name, **{k: res.get(k) for k in
                ("wrote", "merged", "row_index", "range_written", "error")}})
    print(f"add {i:02d}: wrote={res.get('wrote')} row={res.get('row_index')} "
          f"err={res.get('error')}")
    time.sleep(THROTTLE)

elapsed = round(time.time() - t0, 1)

# teardown: delete the synthetic block (contiguous, inclusive)
time.sleep(1.5)
vals2 = ws.get_all_values()
hits = [idx for idx, r in enumerate(vals2, start=1)
        if r and r[0].strip().startswith(PREFIX)]
teardown = {"hit_rows": hits, "deleted": 0, "contiguous": False}
if hits:
    first, last = min(hits), max(hits)
    teardown["contiguous"] = (hits == list(range(first, last + 1)))
    if teardown["contiguous"]:
        ws.delete_rows(first, last)
        teardown.update({"deleted": len(hits), "range": f"{first}-{last}"})
        print(f"teardown: delete_rows({first}, {last}) inclusive -> {len(hits)} rows")
time.sleep(1.5)
vals3 = ws.get_all_values()
leftover = sum(1 for r in vals3[1:] if r and r[0].strip().startswith(PREFIX))
named_after = sum(1 for r in vals3[1:] if r and r[0].strip())
ws2 = connect_worksheet()
grid_after = sheets_sync._worksheet_grid_rows(ws2)

summary = {
    "adds_attempted": N, "adds_written": written, "raw_api_errors": raw_api_errors,
    "elapsed_secs": elapsed, "grid_before": grid_before, "grid_after": grid_after,
    "named_before": named_before, "named_after": named_after,
    "leftover_probe_rows": leftover,
    "teardown": {k: v for k, v in teardown.items() if k != "hit_rows"},
    "pass": (raw_api_errors == 0 and written == N and leftover == 0
             and named_after == 113 and grid_after == grid_before),
}
(OUT / "t1_r31_bulk_summary.json").write_text(
    json.dumps(summary, indent=2), encoding="utf-8")
with (OUT / "t1_r31_bulk_ops_log.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(ops[0].keys()))
    w.writeheader()
    w.writerows(ops)
print(json.dumps(summary, indent=2))
