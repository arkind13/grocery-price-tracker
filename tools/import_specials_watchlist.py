"""One-time Special Watchlist seeder (user ask 2026-11-14/15).

Parses Woolworths_Specials.docx (the saved specials panel — a direct
copy-paste of the site's list) with the SAME specials_parser the old
Wednesday flow used, then posts every item to the site's import endpoint
(POST /api/shopping/watch/import), which matches each name to the weekly
Woolworths catalogue copy and tags it listTag:'stock' — the recorded name
is the CATALOGUE's own product name (the store's spelling — the best
search keyword, exactly what the old sheet's col-G keywords approximated).

Usage (from the repo root, anaconda python):
  python tools/import_specials_watchlist.py --dry   # show the parsed items
  python tools/import_specials_watchlist.py         # parse + POST

The site session cookie comes from the VPS container (JWT_SECRET mint),
so this must be pointed at the VPS app (default https://169-58-107-0.sslip.io
needs a session — run via SSH instead: parse --json here, POST there).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extractors.specials_parser import parse_specials_docx  # noqa: E402


def parsed_items(path: str) -> list[dict]:
    items = parse_specials_docx(path)
    return [
        {
            "name": it.raw_name,
            "size": it.size or None,
            "price": it.price,
            "deal": it.special_desc or None,
        }
        for it in items
        if it.raw_name
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docx", default=str(ROOT / "Woolworths_Specials.docx"))
    ap.add_argument("--json", action="store_true", help="print the parsed items as JSON (for the SSH side)")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    items = parsed_items(args.docx)
    print(f"parsed {len(items)} items from {args.docx}", file=sys.stderr)
    if args.dry or args.json:
        print(json.dumps(items))
        return 0
    print("use --json and POST from the VPS (session) — see module docstring")
    return 0


if __name__ == "__main__":
    sys.exit(main())
