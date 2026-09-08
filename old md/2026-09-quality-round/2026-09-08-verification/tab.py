"""Read/verify Local_Deals tab cells (read-only).

Usage:
  python tab.py row <n>            -> dump row n
  python tab.py find <substring>   -> rows whose Col A contains substring
  python tab.py cell <row> <col>   -> one cell (1-based)
  python tab.py count              -> number of grid rows
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from core.sheets_client import connect_worksheet  # noqa: E402


def main():
    ws = connect_worksheet("Local_Deals")
    mode = sys.argv[1]
    if mode == "row":
        r = ws.get("A%d:J%d" % (int(sys.argv[2]), int(sys.argv[2])))
        for i, v in enumerate((r[0] if r else []), start=1):
            if v:
                print(f"C{i}: {v!r}")
    elif mode == "find":
        vals = ws.get_all_values()
        for i, row in enumerate(vals, start=1):
            if row and sys.argv[2].lower() in (row[0] or "").lower():
                print(f"row {i}: {row}")
    elif mode == "cell":
        print(repr(ws.cell(int(sys.argv[2]), int(sys.argv[3])).value))
    elif mode == "count":
        print(len(ws.get_all_values()))
    else:
        print("unknown mode")


if __name__ == "__main__":
    main()
