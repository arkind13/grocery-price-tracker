#!/usr/bin/env python3
"""One-off: (re)populate the ALDI_Specials_Feed sheet tab from the
CURRENT ALDI drop (the newest promotion whose key <= today) — no
Telegram post, no state change (the cron already posted the drop).

Used 2026-10-09 to backfill the feed for the deal board's live ALDI
lens after the 2026-10-07 Wednesday drop posted but the board stayed
on its frozen sample. Safe to re-run: derived data, full rewrite.
Future drops don't need this — the hourly cron's run_scan writes the
feed itself. Run inside the VPS container or on the PC:
  python3 tools/aldi_feed_now.py [date_iso]
"""
from __future__ import annotations

import sys
from pathlib import Path

_TRACKER = Path(__file__).resolve().parents[1]
for _p in (str(_TRACKER), str(_TRACKER.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.board_feed import write_aldi_feed                # noqa: E402
from core.sydney_time import sydney_today                 # noqa: E402
from extractors.aldi_extractor import (                   # noqa: E402
    fetch_aldi_specials, fetch_promotion_tree)


def main() -> int:
    today = sys.argv[1] if len(sys.argv) > 1 \
        else sydney_today().isoformat()
    promos = fetch_promotion_tree()
    keys = sorted(str(p.get("key") or "") for p in promos)
    current = [k for k in keys if k <= today]
    if not current:
        print(f"[aldi-feed-now] no drop on/before {today}")
        return 1
    drop = current[-1]
    promo = next(p for p in promos if str(p.get("key")) == drop)
    items = fetch_aldi_specials(drop)
    if not items:
        print(f"[aldi-feed-now] drop {drop} has no priced items")
        return 1
    n = write_aldi_feed(items, promo, drop)
    if n < 0:
        print("[aldi-feed-now] feed write FAILED (logged above)")
        return 2
    print(f"[aldi-feed-now] {n} item(s) written for drop {drop} "
          f"({promo.get('title')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
