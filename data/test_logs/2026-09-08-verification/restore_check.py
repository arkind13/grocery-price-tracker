"""§8 final gates: restore all data state files from baselines, then
verify (a) every state file hash matches the pre-round baseline and
(b) Products_Master + Local_Deals grids are 0-drift.

Usage: python restore_check.py restore   # copy baselines back
       python restore_check.py check     # hash + grid verification only
"""
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parents[2]          # grocery-price-tracker/
DATA = REPO / "data"
BASE = HERE / "baselines"
STATE_FILES = [p for p in BASE.iterdir()
               if p.suffix in (".txt", ".json") and p.name != "sheet_snapshot.json"
               and p.name != "local_deals_tab.json"
               and p.name != "data_hashes_before.txt"
               and (DATA / p.name).exists()]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def restore():
    n = 0
    for p in STATE_FILES:
        target = DATA / p.name
        if sha(target) != sha(p):
            target.write_bytes(p.read_bytes())
            print(f"restored {p.name}")
            n += 1
        time.sleep(0.05)
    print(f"restore pass: {n} file(s) rewritten, "
          f"{len(STATE_FILES)} checked")


def check():
    sys.path.insert(0, str(REPO))
    from core.sheets_client import connect_worksheet
    bad = []
    for p in STATE_FILES:
        target = DATA / p.name
        if not target.exists() or sha(target) != sha(p):
            bad.append(p.name)
    print(f"state files vs baseline: {len(STATE_FILES) - len(bad)}/"
          f"{len(STATE_FILES)} identical" + (f"  DIFFERING: {bad}" if bad else ""))

    ws = connect_worksheet()
    now = ws.get_all_values()
    snap = json.loads((BASE / "sheet_snapshot.json").read_text(encoding="utf-8"))
    drift = [(r + 1, c + 1) for r in range(max(len(snap), len(now)))
             for c in range(max(len(snap[r] if r < len(snap) else []),
                                len(now[r] if r < len(now) else [])))
             if (snap[r][c] if r < len(snap) and c < len(snap[r]) else "")
             != (now[r][c] if r < len(now) and c < len(now[r]) else "")]
    print(f"Products_Master drift vs baseline: {len(drift)} {drift[:6]}")

    ws2 = connect_worksheet("Local_Deals")
    now2 = ws2.get_all_values()
    snap2 = json.loads((BASE / "local_deals_tab.json").read_text(encoding="utf-8"))
    drift2 = [(r + 1, c + 1) for r in range(max(len(snap2), len(now2)))
              for c in range(max(len(snap2[r] if r < len(snap2) else []),
                                 len(now2[r] if r < len(now2) else [])))
              if (snap2[r][c] if r < len(snap2) and c < len(snap2[r]) else "")
              != (now2[r][c] if r < len(now2) and c < len(now2[r]) else "")]
    print(f"Local_Deals drift vs baseline: {len(drift2)} {drift2[:6]}")
    return not bad and not drift and not drift2


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "restore":
        restore()
    else:
        ok = check()
        print("GATES", "PASS" if ok else "FAIL")
