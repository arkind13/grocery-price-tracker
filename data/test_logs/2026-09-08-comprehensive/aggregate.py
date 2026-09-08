"""Aggregate all test evidence into the final report tables."""
import csv
import json
from collections import Counter
from pathlib import Path

LOGDIR = Path(__file__).parent

# ---- 1. CLI command battery
rows = [r for r in csv.DictReader((LOGDIR / "commands_log.csv").open(encoding="utf-8")) if r.get("id")]
print(f"== CLI command battery: {len(rows)} commands")
by_area = Counter()
for r in rows:
    area = r["id"].split(".")[0]
    by_area[area] += 1
print("  per area:", dict(by_area))
bad = [(r["id"], r["rc"]) for r in rows if r["rc"] != "0"]
print(f"  non-zero rc (error-path tests): {len(bad)}")
slow = sorted(rows, key=lambda r: -float(r["secs"]))[:5]
print("  slowest:", [(r['id'], r['secs'] + 's') for r in slow])

# ---- 2. T8 ops
t8 = [r for r in csv.reader((LOGDIR / "t8_ops_log.csv").open(encoding="utf-8")) if r]
hdr, ops = t8[0], t8[1:]
fails = [o for o in ops if o[-1] == "FAIL"]
print(f"\n== T8 500-item battery: {len(ops)} logged ops, {len(fails)} FAIL")
op_kinds = Counter(o[3].split(":")[0] for o in ops)
print("  op kinds:", dict(op_kinds))
items = set(o[1] for o in ops)
print(f"  distinct items touched: {len(items)}")

# ---- 3. summary json
s = json.loads((LOGDIR / "t8_summary.json").read_text(encoding="utf-8"))
print("\n== T8 summary json:")
for k in ("items_total", "real_items", "synth_items", "synth_verify_pass",
          "synth_verify_fail", "dup_refused", "reorder_merge_ok",
          "leftover_synth_rows", "final_drift_cells"):
    print(f"  {k}: {s.get(k)}")
print(f"  hard_failures: {len(s.get('hard_failures', []))}")

# ---- 4. manifest
mani = list(csv.DictReader((LOGDIR / "t8_items_manifest.csv").open(encoding="utf-8")))
print(f"\n== Manifest: {len(mani)} items (real: "
      f"{sum(1 for m in mani if m['kind']=='real')}, synth: "
      f"{sum(1 for m in mani if m['kind']=='synth')})")
