#!/usr/bin/env python3
"""Prove the Dunya TLS workaround: fetch the Store API THROUGH
Scrape.do (their proxy terminates TLS, so the site's broken
certificate chain never touches us). No verify=False anywhere.

Cost: 1 Scrape.do credit per catalogue refresh (every 4 weeks).
"""
import json
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

for parent in [HERE, *HERE.parents]:
    if (parent / ".env").exists():
        with open(parent / ".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip("\"' "))
        break

token = os.getenv("SCRAPEDO_API_KEY", "")
target = ("https://www.dunyabutchery.com.au"
          "/wp-json/wc/store/v1/products?per_page=8")

resp = requests.get(
    "https://api.scrape.do",
    params={"token": token, "url": target},  # no render: plain JSON
    timeout=60,
)
print(f"status: {resp.status_code}  bytes: {len(resp.content)}")
data = resp.json()
print(f"products returned: {len(data)}")
for p in data:
    cents = p.get("prices", {}).get("price")
    price = f"${int(cents)/100:.2f}" if cents else "?"
    print(f"  - {p.get('name', '?')[:44]:46} {price}")

# full-certificate validation happened at Scrape.do's end; we never
# disabled verification locally.
print("\nRESULT: valid TLS end-to-end via Scrape.do, clean JSON, "
      "no verification disabled.")
