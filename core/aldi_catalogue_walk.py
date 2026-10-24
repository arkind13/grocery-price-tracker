#!/usr/bin/env python3
"""ALDI CATALOGUE WALKER — LAPTOP SIDE (2026-10-24, user ruling: "aldi and
wool will still use the local computer only coles will go apify route").
The Wednesday task runs THIS then the WW walk back-to-back from 5:00am.

Same logic as the proven server-side walk (ai-studio sidecar
/aldi-catalogue/walk), executed locally:
  * tree: the site's own /products page links (/products/<super>/k/<id>)
  * aisle listing: GET api.aldi.com.au/v3/product-search?categoryTree=<id>
    + offset pagination (30/page, the tracker's curl_cffi plumbing)
  * scope (user rulings 2026-10-23): PLAIN grocery aisles only — campaign
    shelves and Special Buys EXCLUDED; change-only price history happens
    at publish; was-price fields recorded as-is if ever shown.

Usage: python core/aldi_catalogue_walk.py [--no-upload] [--polite-ms 900]
Output: data/aldi-catalogue/walk-YYYY-MM-DD.jsonl.gz + summary; uploads to
/api/shopping/catalogue/aldi-upload (same token as the WW agent).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACKER = HERE.parent
sys.path.insert(0, str(TRACKER))
DATA_DIR = TRACKER / "data" / "aldi-catalogue"
BASE = "https://www.aldi.com.au/products"
SYDNEY = timezone(timedelta(hours=11))
CAMPAIGN_SUPERS = {"lower-prices", "super-savers", "limited-time-only"}

UPLOAD_URL = os.getenv("ALDI_UPLOAD_URL", "https://169-58-107-0.sslip.io/api/shopping/catalogue/aldi-upload")
UPLOAD_TOKEN = os.getenv("WW_UPLOAD_TOKEN", os.getenv("CATALOGUE_UPLOAD_TOKEN", ""))


def log(msg: str) -> None:
    print(f"[aldi-walk {datetime.now(SYDNEY).strftime('%H:%M:%S')}] {msg}", flush=True)


def site_categories() -> list[dict]:
    from curl_cffi import requests as crx

    r = crx.get(BASE, impersonate="chrome131",
                headers={"Accept": "text/html", "Referer": "https://www.aldi.com.au/"}, timeout=30)
    r.raise_for_status()
    links = re.findall(r'href="(/products(?:/[a-z0-9-]+)+/k/(\d+))"', r.text)
    supers, seen = {}, set()
    for href, cid in links:
        if cid in seen:
            continue
        seen.add(cid)
        segs = href[len("/products/"):].split("/")
        if len(segs) == 3 and segs[0] not in CAMPAIGN_SUPERS:
            supers[cid] = segs[0]
    return [{"id": cid, "slug": slug} for cid, slug in supers.items()]


def row_of(p: dict) -> dict | None:
    price = p.get("price") or {}
    amount = price.get("amount")
    name = str(p.get("name") or "").strip()
    code = str(p.get("sku") or "")
    if not name or not code or amount is None or float(amount) <= 0:
        return None
    cats = " > ".join(str(c.get("name") or "") for c in (p.get("categories") or []))
    assets = p.get("assets") or []
    return {
        "store": "aldi", "storeProductId": code, "name": name,
        "brand": str(p.get("brandName") or ""),
        "size": str(p.get("sellingSize") or ""),
        "price": round(float(amount) / 100.0, 2),
        "unitPrice": str(price.get("comparisonDisplay") or ""),
        "isSpecial": bool(price.get("wasPriceDisplay") or price.get("savingsDisplay")),
        "wasPrice": price.get("wasPriceDisplay"),
        "categoryPath": cats,
        "urlSlug": str(p.get("urlSlugText") or ""),
        "image": str(assets[0].get("url") or "") if assets and isinstance(assets[0], dict) else "",
    }


def walk(polite_ms: int, max_pages: int) -> dict:
    from extractors import aldi_extractor as ae

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(SYDNEY).date().isoformat()
    out_path = DATA_DIR / f"walk-{today}.jsonl.gz"
    summary_path = DATA_DIR / f"walk-{today}.summary.json"
    t0 = time.time()
    tree = site_categories()
    log(f"tree: {len(tree)} grocery supers")
    products: dict[str, dict] = {}
    per_super, failures, pages = [], [], 0
    for sup in tree:
        try:
            first = ae._aldi_get("/v3/product-search", {"categoryTree": sup["id"]})
            pages += 1
            total = int((((first.get("meta") or {}).get("pagination") or {}).get("totalCount") or 0))
            new_here = 0
            for p in (first.get("data") or []):
                row = row_of(p)
                if row and row["storeProductId"] not in products:
                    products[row["storeProductId"]] = row
                    new_here += 1
            offset = len(first.get("data") or [])
            while offset < total and pages < max_pages:
                time.sleep(polite_ms / 1000.0)
                page = ae._aldi_get("/v3/product-search", {"categoryTree": sup["id"], "offset": offset})
                pages += 1
                rows = page.get("data") or []
                if not rows:
                    break
                for p in rows:
                    row = row_of(p)
                    if row and row["storeProductId"] not in products:
                        products[row["storeProductId"]] = row
                        new_here += 1
                offset += len(rows)
            per_super.append({"slug": sup["slug"], "apiTotal": total, "new": new_here, "ok": True})
            log(f"  {sup['slug']}: {new_here} new ({total} listed)")
        except Exception as exc:
            failures.append({"slug": sup["slug"], "error": str(exc)[:200]})
            per_super.append({"slug": sup["slug"], "ok": False, "error": str(exc)[:200]})
            log(f"  {sup['slug']}: FAILED {exc}")
        time.sleep(polite_ms / 1000.0)
    with gzip.open(out_path, "at", encoding="utf-8") as fz:
        for row in products.values():
            fz.write(json.dumps(row, default=str) + "\n")
    elapsed = round(time.time() - t0, 1)
    summary = {"ok": not failures, "date": today, "uniqueProducts": len(products),
               "pagesFetched": pages, "failures": failures, "elapsedS": elapsed,
               "perSuper": per_super, "output": str(out_path)}
    summary_path.write_text(json.dumps(summary, indent=1))
    log(f"WALK DONE: {len(products)} products, {pages} pages, {elapsed}s -> {out_path.name}")
    return summary


def upload(summary: dict) -> bool:
    import urllib.request

    if not UPLOAD_TOKEN:
        log("upload skipped: no token")
        return False
    body = Path(summary["output"]).read_bytes()
    req = urllib.request.Request(UPLOAD_URL, data=body, method="POST", headers={
        "Content-Type": "application/gzip", "Authorization": f"Bearer {UPLOAD_TOKEN}",
        "X-Walk-Summary": json.dumps({k: summary.get(k) for k in ("date", "uniqueProducts", "pagesFetched", "elapsedS", "failures")})})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            resp = json.loads(r.read().decode())
            log(f"upload OK: {json.dumps(resp)[:300]}")
            return bool(resp.get("ok"))
    except Exception as exc:
        log(f"upload FAILED: {exc}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--polite-ms", type=int, default=900)
    args = ap.parse_args()
    summary = walk(args.polite_ms, 500)
    ok = False if args.no_upload else upload(summary)
    print(f"ALDI walk: {summary['uniqueProducts']} products / {summary['elapsedS']}s; upload {'ok' if ok else 'skipped/failed'}")
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
