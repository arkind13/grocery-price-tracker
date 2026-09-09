"""One-shot FULL Google Sheet backup (v2 rebuild Round 1).

Primary path: copies the grocery spreadsheet (EVERY tab) to a new
spreadsheet named grocery-tracker-backup-YYYY-MM-DD, then re-opens the
copy and verifies each tab's row count + row width against the source.

Fallback path (observed 2026-09-09: the service account's Drive
storage quota limit is 0 — Google bars service accounts from owning
new Drive files, so files.copy can never succeed): dumps every tab's
COMPLETE grid to backups/grocery-tracker-backup-YYYY-MM-DD.json and
verifies by read-back. The JSON is the restore artifact.

Exit 0 = every tab verified; exit 1 = any mismatch or failure (the
copy / file is kept for inspection). Never prints secret values.

Run from the tracker root:
  anaconda3/python.exe tools/sheet_backup.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.sheets_client import connect_spreadsheet  # noqa: E402


def tab_counts(spreadsheet) -> list[tuple[str, int, int]]:
    """[(title, data-row count, max row width)] for every tab."""
    out: list[tuple[str, int, int]] = []
    for ws in spreadsheet.worksheets():
        grid = ws.get_all_values() or []
        width = max((len(r) for r in grid), default=0)
        out.append((ws.title, len(grid), width))
    return out


def compare_counts(src: list[tuple[str, int, int]],
                   dst: list[tuple[str, int, int]]) -> list[str]:
    """Mismatch lines ('Products_Master: 113x19 -> 110x19'); empty =
    identical (order-insensitive by title). Missing tabs mismatch."""
    dst_map = {t: (r, w) for t, r, w in dst}
    lines: list[str] = []
    for title, rows, width in src:
        got = dst_map.get(title)
        if got is None:
            lines.append(f"{title}: MISSING from backup")
        elif got != (rows, width):
            lines.append(f"{title}: {rows}x{width} -> "
                         f"{got[0]}x{got[1]}")
    return lines


def local_backup(src, title: str) -> tuple[str, list[tuple[str, int,
                                                            int]],
                                            list[str]]:
    """FULL local fallback: every tab's complete grid -> backups/
    <title>.json, verified by read-back against the live snapshot.

    Returns (path, tab counts, mismatch lines)."""
    from json import dumps, loads

    out_dir = Path(__file__).resolve().parents[1] / "backups"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{title}.json"
    grids = {ws.title: (ws.get_all_values() or [])
             for ws in src.worksheets()}
    path.write_text(dumps(grids, ensure_ascii=False),
                    encoding="utf-8")
    counts = [(t, len(g), max((len(r) for r in g), default=0))
              for t, g in grids.items()]
    reread = loads(path.read_text(encoding="utf-8"))
    reread_counts = [(t, len(g), max((len(r) for r in g), default=0))
                     for t, g in reread.items()]
    return str(path), counts, compare_counts(counts, reread_counts)


def main() -> int:
    from datetime import date
    try:
        src = connect_spreadsheet()
        title = f"grocery-tracker-backup-{date.today():%Y-%m-%d}"
        before = tab_counts(src)
        try:
            # gspread 6.2.1: Spreadsheet has no .copy() and
            # Spreadsheet.client is the low-level HTTPClient —
            # authorize a fresh HIGH-LEVEL client on the same
            # credentials for the Drive files.copy.
            import gspread

            from core.sheets_client import (_build_credentials,
                                            _load_env)

            _load_env()
            gc = gspread.authorize(_build_credentials())
            dst = gc.copy(src.id, title=title)
            where = (f"https://docs.google.com/spreadsheets/"
                     f"d/{dst.id}/edit")
            print(f"[backup] copy created: {title}")
            print(f"[backup] {where}")
            problems = compare_counts(before, tab_counts(dst))
        except Exception as copy_exc:  # noqa: BLE001 — fallback path
            print(f"[backup] Drive copy unavailable: {copy_exc}")
            where, counts, problems = local_backup(src, title)
            print(f"[backup] LOCAL fallback written: {where}")
        for t, rows, width in before:
            mark = "FAIL" if any(t in p for p in problems) else "ok"
            print(f"[backup] {mark}: {t} {rows} rows x {width} cols")
        if problems:
            print("[backup] VERIFICATION FAILED:")
            for p in problems:
                print(f"  • {p}")
            return 1
        print("[backup] BACKUP VERIFIED — all tabs match")
        return 0
    except Exception as exc:  # noqa: BLE001 — secret-free report
        print(f"[backup] FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
