#!/usr/bin/env python3
"""WW CATALOGUE WALKER (Phase B of the catalogue-first plan, 2026-10-23).

The LAPTOP AGENT: walks Woolworths' entire first-party range by aisle from
the user's HOME internet (residential IP — exactly what Akamai doesn't
block), politely (~1 page / 2.5 s), resumable per aisle, and writes a
JSONL.gz for upload to the VPS publisher endpoint.

How (all proven live from this PC, 2026-10-23):
  * category tree: GET  /apis/ui/PiesCategoriesWithSpecials (full tree with
    NodeIds; the site's own nav)
  * aisle listing: POST /apis/ui/browse/category  {categoryId, pageNumber,
    pageSize: 36, sortType: TraderRelevance} on a cookie-warmed
    curl_cffi chrome session (the BMSM sweep's proven pattern)
  * every row carries Stockcode, Barcode (GTIN), Brand, PackageSize,
    Price/WasPrice/IsOnSpecial/IsHalfPrice/SavingsAmount (discount captured
    VERBATIM per the user's 2026-10-23 ruling), CentreTag.MultibuyData
    (multi-buy qty+price), CupString (unit price as worded).

Scope: the FULL first-party range; pseudo-shop nodes EXCLUDED (Specials
shelf = duplicates of home aisles; Everyday Market = 3P marketplace —
also filtered by IsMarketProduct; Healthylife = separate storefront;
Container Bonus Credits = credits).

Usage:
  python core/ww_catalogue_walk.py                 # full walk + upload
  python core/ww_catalogue_walk.py --no-upload     # walk only
  python core/ww_catalogue_walk.py --supers pantry,drinks   # partial re-walk
  python core/ww_catalogue_walk.py --polite-ms 1500
Output: data/ww-catalogue/walk-YYYY-MM-DD.jsonl.gz + walk-YYYY-MM-DD.summary.json
State:  data/ww-catalogue/state.json (resume marker per aisle)
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRACKER = HERE.parent
DATA_DIR = TRACKER / "data" / "ww-catalogue"
BASE = "https://www.woolworths.com.au"
PIES = f"{BASE}/apis/ui/PiesCategoriesWithSpecials"
BROWSE = f"{BASE}/apis/ui/browse/category"
PAGE_SIZE = 36
# pseudo-shop top nodes that are NOT part of the first-party grocery range
# pseudo-shop nodes + merchandising VIEWS (cross-aisle curations like
# "Back to School" 3.3k items — their members live in true departments;
# attribution + pages wasted — live-caught 2026-10-23)
EXCLUDE_NODES = {"specialsgroup", "1_A363395", "1_F89E4BB", "1_1D9FEE2",
                 "1_90E697B", "1_8AD6702", "1_9E92C35", "1_BC1E589",
                 # Front of Store (gift cards & co): user 2026-10-24 "gift
                 # cards - i dont need this aisle you can ignore this in all
                 # our future runs"
                 "1_B63CF9E"}
SYDNEY = timezone(timedelta(hours=11))

UPLOAD_URL = os.getenv("WW_UPLOAD_URL", "https://169-58-107-0.sslip.io/api/shopping/catalogue/ww-upload")
UPLOAD_TOKEN = os.getenv("WW_UPLOAD_TOKEN", "")


def log(msg: str) -> None:
    print(f"[ww-walk {datetime.now(SYDNEY).strftime('%H:%M:%S')}] {msg}", flush=True)


def new_session():
    from curl_cffi import requests as crx

    sess = crx.Session(impersonate="chrome")
    try:
        sess.get(f"{BASE}/shop", timeout=30)
    except Exception:
        pass
    return sess


def fetch_tree(sess) -> list[dict]:
    r = sess.get(PIES, headers={"Accept": "application/json", "Referer": f"{BASE}/shop"}, timeout=40)
    r.raise_for_status()
    return [
        c for c in r.json().get("Categories", [])
        if c.get("NodeId") not in EXCLUDE_NODES
    ]


def normalise(p: dict, super_node: dict) -> dict | None:
    code = p.get("Stockcode")
    name = str(p.get("DisplayName") or p.get("Name") or "").strip()
    price = p.get("Price")
    if not code or not name or price is None:
        return None
    if p.get("IsMarketProduct"):  # 3P marketplace — not the WW shelf
        return None
    centre = p.get("CentreTag") or {}
    mb = centre.get("MultibuyData") or {}
    return {
        "store": "woolworths",
        "storeProductId": str(code),
        "name": name,
        "nameBare": str(p.get("Name") or ""),
        "brand": str(p.get("Brand") or ""),
        "barcode": str(p.get("Barcode") or "") or None,
        "size": str(p.get("PackageSize") or ""),
        "price": float(price),
        "instorePrice": p.get("InstorePrice"),
        "unitPrice": str(p.get("CupString") or ""),
        # ---- DEAL CAPTURE (user ruling: verbatim the way the site says it) --
        "isSpecial": bool(p.get("IsOnSpecial")),
        "wasPrice": (p.get("WasPrice") if p.get("WasPrice") and p.get("WasPrice") != price else None),
        "savingsAmount": p.get("SavingsAmount"),
        "isHalfPrice": bool(p.get("IsHalfPrice")),
        "multibuyQty": mb.get("Quantity"),
        "multibuyPrice": mb.get("Price"),
        "promotionType": centre.get("PromotionType") or None,
        "tagText": centre.get("TagContentText") or centre.get("TagContent") or None,
        "superAisle": super_node.get("Description") or "",
        "sapCategories": p.get("SapCategories"),
        "urlSlug": str(p.get("UrlFriendlyName") or ""),
        "image": str(p.get("SmallImageFile") or p.get("MediumImageFile") or ""),
        "isTobacco": bool(p.get("IsTobacco")),
    }


def walk(polite_ms: int, supers_filter: set[str] | None, max_pages: int) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state_path = DATA_DIR / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": []}
    today = datetime.now(SYDNEY).date().isoformat()
    out_path = DATA_DIR / f"walk-{today}.jsonl.gz"
    summary_path = DATA_DIR / f"walk-{today}.summary.json"

    sess = new_session()
    tree = fetch_tree(sess)
    log(f"tree: {len(tree)} walkable supers")
    if supers_filter:
        tree = [c for c in tree if (c.get("UrlFriendlyName") or "") in supers_filter
                or (c.get("Description") or "").lower() in supers_filter]

    resume = today == state.get("date")
    done = set(state.get("done", [])) if resume else set()
    products: dict[str, dict] = {}
    flushed: set[str] = set()
    per_super, failures = [], []
    pages = 0
    t0 = time.time()
    for sup in tree:
        sid = sup.get("NodeId")
        slug = sup.get("UrlFriendlyName") or ""
        desc = sup.get("Description") or slug
        if sid in done:
            per_super.append({"id": sid, "slug": slug, "note": "resumed-done"})
            continue
        aisle_products = 0
        try:
            page_no, total = 1, None
            while True:
                r = sess.post(BROWSE, json={
                    "categoryId": sid, "url": f"/shop/browse/{slug}", "formatObject": "{}",
                    "pageNumber": page_no, "pageSize": PAGE_SIZE, "sortType": "TraderRelevance",
                }, headers={"Origin": BASE, "Referer": f"{BASE}/shop/browse/{slug}",
                            "Content-Type": "application/json", "Accept": "application/json"},
                    timeout=40)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                d = r.json()
                total = int(d.get("TotalRecordCount") or 0)
                rows = [p for b in (d.get("Bundles") or []) for p in (b.get("Products") or [])]
                if not rows:
                    break
                for p in rows:
                    row = normalise(p, sup)
                    if row and row["storeProductId"] not in products:
                        products[row["storeProductId"]] = row
                        aisle_products += 1
                pages += 1
                if page_no * PAGE_SIZE >= total or pages >= max_pages:
                    break
                page_no += 1
                time.sleep(polite_ms / 1000.0)
            per_super.append({"id": sid, "slug": slug, "apiTotal": total,
                              "walked": aisle_products, "ok": True})
            log(f"  {desc}: {aisle_products} unique ({total} listed)")
        except Exception as exc:  # one aisle failing never loses the walk
            failures.append({"slug": slug, "error": str(exc)[:200]})
            per_super.append({"id": sid, "slug": slug, "ok": False, "error": str(exc)[:200]})
            log(f"  {desc}: FAILED {exc}")
            continue
        # flush THIS aisle's rows now (crash-safe: a killed run keeps every
        # finished aisle; duplicates across aisles are deduped at publish)
        with gzip.open(out_path, "at", encoding="utf-8") as fz:
            seen_now = set()
            for code, row in products.items():
                if code in seen_now or code in flushed:
                    continue
                seen_now.add(code)
                flushed.add(code)
                fz.write(json.dumps(row, default=str) + "\n")
        state["date"], state["done"] = today, sorted(done | {sid} | {s["id"] for s in per_super if s.get("ok")})
        state_path.write_text(json.dumps(state))
        time.sleep(polite_ms / 1000.0)

    elapsed = round(time.time() - t0, 1)
    summary = {
        "ok": not failures, "date": today, "supersWalked": len(tree),
        "uniqueProducts": len(products), "pagesFetched": pages,
        "failures": failures, "elapsedS": elapsed, "perSuper": per_super,
        "output": str(out_path),
    }
    summary_path.write_text(json.dumps(summary, indent=1))
    log(f"WALK DONE: {len(products)} unique products, {pages} pages, {elapsed}s, "
        f"{len(failures)} failures -> {out_path.name}")
    return summary


def telegram(msg: str) -> None:
    """Best-effort receipt (env TELEGRAM_CLAW_BOT + TELEGRAM_CHAT_ID)."""
    try:
        import urllib.request

        bot = os.getenv("TELEGRAM_CLAW_BOT", "")
        chat = os.getenv("TELEGRAM_CHAT_ID", "")
        if not bot or not chat:
            return
        url = f"https://api.telegram.org/bot{bot}/sendMessage"
        data = json.dumps({"chat_id": chat, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data,
                                      headers={"Content-Type": "application/json"}), timeout=15)
    except Exception:
        pass


def upload(summary: dict) -> bool:
    import urllib.request

    path = Path(summary["output"])
    if not UPLOAD_TOKEN:
        log("upload skipped: no WW_UPLOAD_TOKEN")
        return False
    body = path.read_bytes()
    req = urllib.request.Request(UPLOAD_URL, data=body, method="POST", headers={
        "Content-Type": "application/gzip",
        "Authorization": f"Bearer {UPLOAD_TOKEN}",
        "X-Walk-Summary": json.dumps({k: summary[k] for k in ("date", "uniqueProducts", "pagesFetched", "elapsedS", "failures")}),
    })
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
    ap.add_argument("--supers", default="", help="comma-separated slugs for a partial re-walk")
    ap.add_argument("--polite-ms", type=int, default=2500)
    ap.add_argument("--max-pages", type=int, default=1200)
    args = ap.parse_args()
    sf = {s.strip() for s in args.supers.split(",") if s.strip()} or None
    summary = walk(args.polite_ms, sf, args.max_pages)
    lines = [
        "🛒 WW CATALOGUE WALK (laptop agent)",
        f"products: {summary['uniqueProducts']} unique / {summary['pagesFetched']} pages / {summary['elapsedS']}s",
        f"aisles ok: {sum(1 for s in summary['perSuper'] if s.get('ok'))}/{summary['supersWalked']}"
        + (f" — FAILED: {', '.join(f['slug'] for f in summary['failures'])}" if summary["failures"] else ""),
    ]
    if not args.no_upload:
        ok = upload(summary)
        lines.append("upload: " + ("✅ published receipt from server" if ok else "❌ FAILED — run 'Run WW walk now.bat' when online"))
    telegram("\n".join(lines))
    print("\n".join(lines))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
