"""Recon/snapshot helper for the 2026-09-08 verification round.

Usage:
  python recon.py snapshot                 -> baselines/sheet_snapshot.json (full grid, retry on 5xx)
  python recon.py diff                     -> full-grid diff vs baselines/sheet_snapshot.json (drift check)
  python recon.py cell <row> <col> <label> -> print one cell value (1-based row/col)
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # grocery-price-tracker/
sys.path.insert(0, str(ROOT))
from core.sheets_client import connect_worksheet  # noqa: E402

BASE = Path(__file__).parent / "baselines"
SNAP = BASE / "sheet_snapshot.json"


def get_ws():
    last = None
    for attempt in range(5):
        try:
            return connect_worksheet()
        except Exception as exc:  # transient 5xx
            last = exc
            wait = 5 * (attempt + 1)
            print(f"connect attempt {attempt+1} failed ({exc}); retry in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"could not connect after retries: {last}")


def snapshot():
    ws = get_ws()
    vals = ws.get_all_values()
    BASE.mkdir(exist_ok=True)
    SNAP.write_text(json.dumps(vals, ensure_ascii=False), encoding="utf-8")
    named = [r[0].strip() for r in vals[1:] if len(r) > 0 and r[0].strip()]
    print(f"SNAPSHOT saved: {len(vals)} grid rows (incl header), {len(named)} named product rows")
    return vals


def diff():
    ws = get_ws()
    now = ws.get_all_values()
    old = json.loads(SNAP.read_text(encoding="utf-8"))
    drift = []
    for r in range(max(len(old), len(now))):
        orow = old[r] if r < len(old) else []
        nrow = now[r] if r < len(now) else []
        for c in range(max(len(orow), len(nrow))):
            ov = orow[c] if c < len(orow) else ""
            nv = nrow[c] if c < len(nrow) else ""
            if ov != nv:
                drift.append((r + 1, c + 1, ov[:60], nv[:60]))
    print(f"DRIFT vs baseline: {len(drift)} cell(s)")
    for r, c, ov, nv in drift[:40]:
        print(f"  R{r}C{c}: {ov!r} -> {nv!r}")
    return drift


def cell(row, col, label=""):
    ws = get_ws()
    v = ws.cell(int(row), int(col)).value
    print(f"{label} R{row}C{col} = {v!r}")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "snapshot":
        snapshot()
    elif mode == "diff":
        diff()
    elif mode == "cell":
        cell(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
    else:
        print("unknown mode")
