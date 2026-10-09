#!/usr/bin/env python3
"""One-off: (re)populate the WW_Specials_Feed sheet tab from the CURRENT
Woolworths_Specials.docx + live Products_Master — NO Telegram posts and
NO writes to any other tab (the full Wednesday run already happened).

Used 2026-10-09 to backfill the feed for the deal board's live Wool
lens. Safe to re-run: the tab is derived data, fully rewritten.
Future runs don't need this — `wednesday` writes the feed itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TRACKER = Path(__file__).resolve().parents[1]
for _p in (str(_TRACKER), str(_TRACKER.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.sheets_client import connect_spreadsheet          # noqa: E402
from core.sydney_time import sydney_today                    # noqa: E402
from core.v2_wednesday import (MASTER_TAB, next_wednesday,   # noqa: E402
                               parse_inputs, write_board_feed)


def main() -> int:
    _main_items, specials_items = parse_inputs()
    if not specials_items:
        print("[board-feed-now] no specials docx items found — nothing "
              "to do (paste Woolworths_Specials.docx first)")
        return 1
    ss = connect_spreadsheet()
    master_ws = ss.worksheet(MASTER_TAB)
    grid = [list(r) for r in (master_ws.get_all_values() or [])]
    today = sydney_today()
    n = write_board_feed(ss, grid, specials_items, today)
    print(f"[board-feed-now] {n} deal row(s) written "
          f"(run {today.isoformat()} -> week ends "
          f"{next_wednesday(today).isoformat()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
