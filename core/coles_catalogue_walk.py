#!/usr/bin/env python3
"""COLES CATALOGUE WALKER (Phase C of the catalogue-first plan, 2026-10-24).

The user's call: "why cant we do coles the same way we did wool from my
local computer rather than going through vps and scrape" — PROVEN RIGHT by
live probing: the home IP gets Coles' full __NEXT_DATA__ pages directly
(no proxy, no render, $0). Coles' bot shield (an Imperva-style challenge)
fires on BURSTS, so this walker is slower and gentler than the WW one:
  * warm-up visit before each aisle batch
  * ~4.5 s between pages (Coles etiquette; WW uses 2.2)
  * challenge detection ("Pardon Our Interruption" / no __NEXT_DATA__) ->
    75 s cool-down, retry x3, then park the aisle and move on
  * per-aisle flush + state.json resume (a challenged run loses nothing)

How (proven live from this PC, 2026-10-24):
  * category tree: searchResults.catalogGroupView on any browse page
    (nodes carry productCount — walk LEAF categories, the WW lesson)
  * aisle listing: GET /browse/<slug>?page=N — __NEXT_DATA__ carries
    searchResults.results[] = the products (name, brand, size, id,
    pricing{now, was, comparable, promotionType, offerDescription?...})

Usage:
  python core/coles_catalogue_walk.py               # full walk + upload
  python core/coles_catalogue_walk.py --no-upload
  python core/coles_catalogue_walk.py --aisles fresh-meat,bacon-ham
Output: data/coles-catalogue/walk-YYYY-MM-DD.jsonl.gz + .summary.json
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
DATA_DIR = TRACKER / "data" / "coles-catalogue"
BASE = "https://www.coles.com.au"
CHALLENGE_MARK = "Pardon Our Interruption"
SYDNEY = timezone(timedelta(hours=11))

UPLOAD_URL = os.getenv("COLES_UPLOAD_URL", "https://169-58-107-0.sslip.io/api/shopping/catalogue/coles-upload")
UPLOAD_TOKEN = os.getenv("WW_UPLOAD_TOKEN", os.getenv("CATALOGUE_UPLOAD_TOKEN", ""))


def log(msg: str) -> None:
    print(f"[coles-walk {datetime.now(SYDNEY).strftime('%H:%M:%S')}] {msg}", flush=True)


class ColesSession:
    """Fetches browse pages through a REAL headless Chromium (Playwright).
    Coles' Imperva shield binds its clearance to the browser fingerprint —
    cookie-borrowing into curl_cffi worked for ~1,000 pages then got
    re-flagged (live 2026-10-24). A genuine engine solves challenges
    invisibly and needs no borrowed cookies — fully Wednesday-automatable."""

    def __init__(self, headless: bool = False):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        # HEADED by default (a visible window): Imperva detects headless
        # Chromium (live-proven 2026-10-24 — headless got the challenge on
        # every page; the ZCode in-app browser engine passed). For the 5am
        # Wednesday task the window appears on the locked session — harmless.
        args = ["--disable-blink-features=AutomationControlled"]
        self.browser = self._pw.chromium.launch(headless=headless, args=args)
        self.page = self.browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1380, "height": 900})
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

    def browse(self, path: str) -> dict | None:
        """One browse page -> pageProps dict (None after retries). The
        challenge (when it appears) auto-solves and redirects in a genuine
        engine — so WAIT for __NEXT_DATA__ up to 20s instead of reloading
        (a reload resets the challenge — live-caught 2026-10-24)."""
        import json as _json
        for attempt in range(3):
            try:
                self.page.goto(f"{BASE}{path}", timeout=60000, wait_until="domcontentloaded")
                try:
                    self.page.wait_for_selector("#__NEXT_DATA__", timeout=20000)
                except Exception:
                    pass  # fall through to the manual read below
                data = self.page.evaluate(
                    "() => { const el = document.getElementById('__NEXT_DATA__'); return el ? el.textContent : null; }")
                if data:
                    return _json.loads(data)["props"]["pageProps"]
                log(f"    no-data on {path} (attempt {attempt+1}/3) — waiting 20s before retry")
                self.page.wait_for_timeout(20000)
            except Exception as exc:
                log(f"    ERR {type(exc).__name__} on {path} (attempt {attempt+1}/3)")
        return None

    def set_cookie_header(self, _):  # pass-keeper compatibility (unused now)
        pass

    def close(self):
        try:
            self.browser.close()
            self._pw.stop()
        except Exception:
            pass


# pseudo-shop nodes that are not real grocery aisles
EXCLUDE_NAMES = {"bonus credit products", "specials", "christmas"}
def flatten_tree(cgv: list[dict]) -> list[dict]:
    """catalogGroupView -> LEAF aisles with their REAL seoToken slugs (the
    site's own URLs — live-caught 2026-10-24: regex-guessed slugs serve
    empty pages). Leaves, not supers — the WW cross-listing lesson."""
    out: list[dict] = []

    def walk(nodes, parents, parent_slugs):
        for n in nodes or []:
            name = str(n.get("name") or "").strip()
            if not name or name.lower() in EXCLUDE_NAMES:
                continue
            kids = n.get("catalogGroupView") or []
            token = str(n.get("seoToken") or "").strip()
            path = parents + [name]
            if kids:
                walk(kids, path, parent_slugs + ([token] if token else []))
            else:
                if not token or not parent_slugs:
                    continue  # a leaf needs its department path to serve products
                out.append({"id": str(n.get("id") or ""), "name": name,
                            "slug": "/".join(parent_slugs + [token]),
                            "productCount": n.get("productCount"),
                            "path": " > ".join(path)})

    walk(cgv, [], [])
    return out


def normalise(p: dict, aisle: dict) -> dict | None:
    if p.get("_type") not in (None, "PRODUCT"):
        return None
    code = p.get("id") or p.get("articleNumber")
    name = str(p.get("name") or "").strip()
    pricing = p.get("pricing") or {}
    price = pricing.get("now")
    if price is None or not code or not name:
        return None
    promo = str(pricing.get("promotionType") or "")
    offer = pricing.get("offerDescription") or ""
    mb = pricing.get("multiBuyPromotion") or {}
    deal_text = None
    deal_type = None
    if offer:
        deal_text, deal_type = str(offer), "other"
    if mb and mb.get("minQuantity") and pricing.get("multiBuyValue"):
        deal_text, deal_type = f"{mb.get('minQuantity')} for ${pricing.get('multiBuyValue')}", "multibuy"
    elif pricing.get("was") and float(pricing.get("was") or 0) > float(price):
        save = float(pricing["was"]) - float(price)
        deal_text, deal_type = f"Was ${float(pricing['was']):.2f} (Save ${save:.2f})", "was-price"
    elif promo == "SPECIAL":
        deal_text, deal_type = "Special", "other"
    return {
        "store": "coles",
        "storeProductId": str(code),
        "name": (f"{name} {p.get('size') or ''}".strip() if p.get("size") else name),
        "nameBare": name,
        "brand": str(p.get("brand") or ""),
        "barcode": str(p.get("gtin") or "") or None,
        "size": str(p.get("size") or ""),
        "price": float(price),
        "unitPrice": str(pricing.get("comparable") or ""),
        "isSpecial": promo in ("SPECIAL", "MULTI_BUY", "EDR_SPECIAL") or bool(offer),
        "wasPrice": (float(pricing["was"]) if pricing.get("was") and float(pricing["was"]) > float(price) else None),
        "promotionType": promo or None,
        "dealText": deal_text, "dealType": deal_type,
        "superAisle": aisle["path"],
        "urlSlug": str(p.get("seoToken") or ""),
        "image": str((p.get("imageUris") or [""])[0] or ""),
    }


def walk(polite_ms: int, aisles_filter: set[str] | None, max_pages: int) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state_path = DATA_DIR / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": []}
    today = datetime.now(SYDNEY).date().isoformat()
    out_path = DATA_DIR / f"walk-{today}.jsonl.gz"
    summary_path = DATA_DIR / f"walk-{today}.summary.json"

    s = ColesSession()
    log("real-engine session started (headless Chromium)")
    log("warm-up + tree: /browse (all categories)")
    allcats = s.browse("/browse")
    if not allcats:
        log("FATAL: challenged even on warm-up — try again later (resume keeps progress)")
        return {"ok": False, "error": "challenged on warm-up"}
    apc = allcats.get("allProductCategories") or {}
    aisles = flatten_tree(apc.get("catalogGroupView") or [])
    leaf_total = sum(int(a["productCount"] or 0) for a in aisles if a["productCount"])
    log(f"tree: {len(aisles)} leaf aisles, ~{leaf_total} listed products")
    seasonal = ("back to school", "halloween", "christmas", "summer", "mother's day", "father's day", "easter")
    aisles.sort(key=lambda a: any(s in a["path"].lower() for s in seasonal))
    if aisles_filter:
        aisles = [a for a in aisles if a["slug"] in aisles_filter or a["name"].lower() in aisles_filter]

    resume = today == state.get("date")
    done = set(state.get("done", [])) if resume else set()
    products: dict[str, dict] = {}
    per_aisle, failures = [], []
    pages = 0
    t0 = time.time()
    ck_path = DATA_DIR / "cookies.txt"  # pass-keeper file (unused with the real engine)
    ck_mtime = 0
    for aisle in aisles:
        slug = aisle["slug"]
        if slug in done:
            per_aisle.append({"slug": slug, "note": "resumed-done"})
            continue

        aisle_new = 0
        listed_total = None
        ok = True
        try:
            page_no = 1
            first_names: list[str] = []
            while True:
                props = s.browse(f"/browse/{slug}" + (f"?page={page_no}" if page_no > 1 else ""))
                if props is None:
                    ok = False
                    break
                sr = props.get("searchResults") or {}
                rows = sr.get("results") or []
                listed_total = sr.get("noOfResults") or 0
                if not listed_total and rows:
                    listed_total = len(rows)  # some aisles report 0 but list a full page
                if not rows:
                    break
                names = [str(r.get("name") or "") for r in rows[:3]]
                if page_no > 1 and names == first_names:
                    break  # same page served — no real pagination beyond here
                if page_no == 1:
                    first_names = names
                for r in rows:
                    row = normalise(r, aisle)
                    if row and row["storeProductId"] not in products:
                        products[row["storeProductId"]] = row
                        aisle_new += 1
                pages += 1
                if listed_total and len(products) and page_no * 36 >= int(listed_total):
                    break
                if pages >= max_pages:
                    break
                page_no += 1
                time.sleep(polite_ms / 1000.0)
        except Exception as exc:  # never lose the walk
            ok = False
            failures.append({"slug": slug, "error": str(exc)[:200]})
        per_aisle.append({"slug": slug, "name": aisle["name"], "apiTotal": listed_total,
                          "walked": aisle_new, "ok": ok})
        log(f"  {aisle['path']}: {aisle_new} new ({listed_total} listed) {'OK' if ok else 'PARKED'}")
        if ok:
            with gzip.open(out_path, "at", encoding="utf-8") as fz:
                for code, row in products.items():
                    fz.write(json.dumps(row, default=str) + "\n")
            products = {}  # flushed
            done.add(slug)
            state["date"], state["done"] = today, sorted(done)
            state_path.write_text(json.dumps(state))
        time.sleep(polite_ms / 1000.0)

    elapsed = round(time.time() - t0, 1)
    summary = {"ok": not failures, "date": today, "aislesWalked": len(aisles),
               "uniqueProducts": "?see gz", "pagesFetched": pages,
               "failures": failures, "elapsedS": elapsed, "perAisle": per_aisle,
               "output": str(out_path)}
    summary_path.write_text(json.dumps(summary, indent=1))
    s.close()
    log(f"WALK DONE: {pages} pages, {elapsed}s, {len(failures)} parked aisles -> {out_path.name}")
    return summary


def telegram(msg: str) -> None:
    try:
        import urllib.request

        bot, chat = os.getenv("TELEGRAM_CLAW_BOT", ""), os.getenv("TELEGRAM_CHAT_ID", "")
        if not bot or not chat:
            return
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{bot}/sendMessage",
            data=json.dumps({"chat_id": chat, "text": msg}).encode(),
            headers={"Content-Type": "application/json"}), timeout=15)
    except Exception:
        pass


def upload(summary: dict) -> bool:
    import urllib.request

    if not UPLOAD_TOKEN:
        log("upload skipped: no token")
        return False
    body = Path(summary["output"]).read_bytes()
    req = urllib.request.Request(UPLOAD_URL, data=body, method="POST", headers={
        "Content-Type": "application/gzip", "Authorization": f"Bearer {UPLOAD_TOKEN}",
        "X-Walk-Summary": json.dumps({k: summary.get(k) for k in ("date", "pagesFetched", "elapsedS", "failures")})})
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
    ap.add_argument("--aisles", default="")
    ap.add_argument("--polite-ms", type=int, default=4500)
    ap.add_argument("--max-pages", type=int, default=2000)
    args = ap.parse_args()
    af = {a.strip() for a in args.aisles.split(",") if a.strip()} or None
    summary = walk(args.polite_ms, af, args.max_pages)
    lines = ["🛒 COLES CATALOGUE WALK (laptop agent)",
             f"pages: {summary.get('pagesFetched')} / {summary.get('elapsedS')}s / parked: {len(summary.get('failures', []))}"]
    if not args.no_upload and summary.get("output"):
        ok = upload(summary)
        lines.append("upload: " + ("✅ published" if ok else "❌ FAILED — re-run later, resume keeps progress"))
    telegram("\n".join(lines))
    print("\n".join(lines))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
