"""Historical board replay — every surviving source artifact through
the FIXED pipeline (user directive 2026-09-27: 'go back to the posts
10 weeks and test them out').

Replays (real vision + verifier calls, READ-ONLY — no sheet writes,
no Telegram):
  - every board image surviving the 14-day retention window
    (data/fb_flyers/*), and
  - the 2026-09-11 Merjan truths (images gone; the user-verified
    table in data/test_logs/cycle-3/merjan-corrections.md is pinned
    as tile-text fixtures in tests/test_pack_guard.py instead).

Run on the VPS container:
  docker exec openclaw-core python3 /app/tasks/ai-tools/\
grocery-price-tracker/tools/replay_boards.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.flyer_vision import parse_board_images  # noqa: E402
from core.local_deals import _digest_items         # noqa: E402

BOARDS = [
    ("Sep15 MER1509261507 (merjan)",
     ["data/fb_flyers/20260915_150835/merjan/"
      "merjan_122189297726942477_2.jpg"]),
    ("Sep17 DUN1709261507 (dunya)",
     ["data/fb_flyers/20260917_150731/dunya/"
      "dunya_1086757197050025_2.jpg"]),
    ("Sep19 MER1909260507 (merjan)",
     ["data/fb_flyers/20260919_050738/merjan/"
      "merjan_122189815568942477_2.jpg"]),
    ("Sep22 FRU2209260507 (fruitopia)",
     ["data/fb_flyers/20260922_050738/fruitopia/"
      "fruitopia_989656004143460_2.jpg",
      "data/fb_flyers/20260922_050738/fruitopia/"
      "fruitopia_989656004143460_3.jpg",
      "data/fb_flyers/20260922_050738/fruitopia/"
      "fruitopia_989656004143460_4.jpg"]),
    ("Sep26 DUN2609260507 (dunya)",
     ["data/fb_flyers/20260926_050826/dunya/"
      "dunya_1093883173004094_2.jpg"]),
    ("Sep26/27 MER2609260507/MER2709260507 (merjan, same image)",
     ["data/fb_flyers/20260926_050826/merjan/"
      "merjan_122191020806942477_2.jpg"]),
    ("Sep27 DUN2709260507 (dunya)",
     ["data/fb_flyers/20260927_050731/dunya/"
      "dunya_1094949772897434_2.jpg"]),
]


def main() -> int:
    print("REPLAY of every surviving board through the fixed "
          "pipeline (read-only)\n")
    total = bundles = flags = 0
    for label, rel in BOARDS:
        files = [ROOT / p for p in rel]
        if not all(f.exists() for f in files):
            print(f"== {label}: SOURCE PRUNED (retention) — skipped")
            continue
        try:
            payload = parse_board_images(files)
        except Exception as exc:               # noqa: BLE001
            print(f"== {label}: FAILED {exc.__class__.__name__}: "
                  f"{exc}")
            continue
        items = _digest_items(payload["deals"])
        b = sum(1 for i in items if i.get("terms"))
        fl = sum(1 for i in items if i.get("review_flag"))
        total += len(items)
        bundles += b
        flags += fl
        print(f"== {label}: {len(items)} deals · {b} with min-order "
              f"terms · {fl} flagged · until="
              f"{payload.get('valid_until')}")
        for i in items:
            mark = " ⚠" + i["review_flag"] if i.get("review_flag") \
                else ""
            print(f"   {i.get('price_text') or '?':>12}  "
                  f"{i.get('name', '')[:34]:36} "
                  f"{i.get('terms') or ''}{mark}")
        print()
    print(f"REPLAY TOTAL: {total} deals · {bundles} bundle terms · "
          f"{flags} flagged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
