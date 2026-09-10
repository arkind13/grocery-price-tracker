#!/usr/bin/env python3
"""Probe Dunya's WooCommerce Store API for a clean product catalogue."""
import json
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"})
# The site's TLS chain fails from this sandbox python; verify=False is
# diagnostic-only here (production can route via Scrape.do or fix the
# chain). curl/Schannel verifies it fine.
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

for path in (
    "/wp-json/wc/store/v1/products?per_page=50",
    "/wp-json/wc/store/products?per_page=50",
    "/wp-json/wc/v3/products?per_page=50",
):
    url = "https://www.dunyabutchery.com.au" + path
    try:
        r = S.get(url, timeout=30, verify=False)
    except requests.RequestException as exc:
        print(f"{path}\n  ERROR {exc.__class__.__name__}")
        continue
    print(f"{path}\n  status={r.status_code} bytes={len(r.content)}")
    if r.status_code != 200:
        print("  body:", r.text[:120].replace("\n", " "))
        continue
    try:
        data = r.json()
    except ValueError:
        print("  not JSON")
        continue
    if isinstance(data, dict):
        print("  keys:", list(data)[:6])
        continue
    print(f"  products: {len(data)}")
    for p in data[:12]:
        name = p.get("name", "?")
        prices = p.get("prices", {})
        price = prices.get("price", "?")
        reg = prices.get("regular_price", "")
        # Woo store API prices are integers in cents (minor units)
        try:
            pf = f"${int(price)/100:.2f}"
        except (TypeError, ValueError):
            pf = str(price)
        cats = ",".join(c.get("name", "") for c in p.get("categories", []))
        print(f"  - {name[:40]:42} {pf:>8}  (reg {reg})  [{cats}]")
    break
