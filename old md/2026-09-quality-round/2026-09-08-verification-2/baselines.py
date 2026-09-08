"""Baseline snapshot for the 2026-09-08-verification-2 round (Round B2).

Usage:
  python baselines.py snapshot   # sheet grids (Products_Master + Local_Deals),
                                 # state-file copies, FULL data/ tree sha256 manifest
  python baselines.py manifest <out-name>   # full data/ tree manifest only
  python baselines.py counts     # lists / todo / missed-pricing counts via read-only sheet math
"""
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parents[2]          # grocery-price-tracker/
sys.path.insert(0, str(REPO))
from core.sheets_client import connect_worksheet, connect_spreadsheet  # noqa: E402

DATA = REPO / "data"
BASE = HERE / "baselines"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree_manifest(out_name: str) -> Path:
    lines = []
    for p in sorted(DATA.rglob("*")):
        if p.is_file():
            rel = p.relative_to(REPO).as_posix()
            lines.append(f"{sha(p)}  {rel}")
    out = BASE / out_name
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"manifest: {len(lines)} files -> {out.name}")
    return out


def snapshot():
    BASE.mkdir(exist_ok=True)
    # 1. sheet grids
    ws = connect_worksheet()
    vals = ws.get_all_values()
    (BASE / "sheet_snapshot.json").write_text(json.dumps(vals, ensure_ascii=False), encoding="utf-8")
    named = [r[0].strip() for r in vals[1:] if len(r) > 0 and r[0].strip()]
    print(f"Products_Master: {len(vals)} grid rows (incl header), {len(named)} named product rows")
    time.sleep(1.5)
    try:
        ss = connect_spreadsheet()
        ld = ss.worksheet("Local_Deals")
        ldv = ld.get_all_values()
        (BASE / "local_deals_tab.json").write_text(json.dumps(ldv, ensure_ascii=False), encoding="utf-8")
        print(f"Local_Deals: {len(ldv)} grid rows")
    except Exception as exc:
        print(f"Local_Deals snapshot FAILED: {exc}")
    # 2. state files (top level only, like prior rounds)
    n = 0
    for p in sorted(DATA.iterdir()):
        if p.is_file() and p.suffix in (".txt", ".json"):
            shutil.copy2(p, BASE / p.name)
            n += 1
    print(f"state files copied: {n}")
    # 3. FULL tree manifest
    tree_manifest("data_full_manifest_before.txt")


def counts():
    ws = connect_worksheet()
    vals = ws.get_all_values()
    named = [r for r in vals[1:] if len(r) > 0 and r[0].strip()]
    ww_missing = sum(1 for r in named if len(r) > 5 and not (r[4] or "").strip() and (r[5] or "").strip())
    coles_missing = sum(1 for r in named if len(r) > 4 and not (r[3] or "").strip() and (r[4] or "").strip())
    print(f"named rows: {len(named)}; ww-missing-with-coles: {ww_missing}; coles-missing-with-ww: {coles_missing}")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "snapshot":
        snapshot()
    elif mode == "manifest":
        tree_manifest(sys.argv[2])
    elif mode == "counts":
        counts()
