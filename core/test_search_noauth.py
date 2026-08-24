"""Test both stores' search without login."""
import os, sys
sys.path.insert(0, "grocery-price-tracker")
from dotenv import load_dotenv
load_dotenv(".env", override=True)

# Woolworths search via curl_cffi (no cookie)
from curl_cffi import requests as cr
r = cr.get(
    "https://www.woolworths.com.au/apis/ui/Search/products",
    params={"searchTerm": "milk", "pageSize": 3},
    impersonate="chrome131",
    headers={"Accept": "application/json", "Referer": "https://www.woolworths.com.au/"},
    timeout=30,
)
print(f"Woolworths search: HTTP {r.status_code}, {len(r.text)} bytes")
if r.status_code == 200:
    data = r.json()
    products = data.get("Products", [{}])[0].get("Products", [])
    print(f"  Found {len(products)} products")
    for p in products[:3]:
        print(f"  {p.get('DisplayName','?')}: ${p.get('Price','?')}")
else:
    print(f"  Failed: {r.text[:200]}")

# Coles search via Scrape.do (no login needed)
from extractors.coles_extractor import search_coles
results = search_coles("milk", 3)
print(f"\nColes search: {len(results)} results")
for r in results[:3]:
    print(f"  {r.raw_name}: ${r.price}")
