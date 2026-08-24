"""Extract JS bundle URLs and search for login API in them."""
import re, sys
from curl_cffi import requests as r

s = r.Session()
resp = s.get("https://www.woolworths.com.au/shop/login", impersonate="chrome131", timeout=30)
html = resp.text

# Find all script tags
scripts = re.findall(r"""<script[^>]*src=["']([^"']+)["'][^>]*>""", html)
print(f"Script tags: {len(scripts)}")
for sc in scripts[:20]:
    print(f"  {sc[:120]}")

# Download main JS bundles and search for login API
import urllib.parse
base = "https://www.woolworths.com.au"

for sc in scripts[:5]:
    if not sc.startswith("http"):
        sc = urllib.parse.urljoin(base, sc)
    print(f"\nFetching: {sc[:120]}")
    try:
        js_resp = r.get(sc, impersonate="chrome131", timeout=30)
        js = js_resp.text
        print(f"  Size: {len(js)} bytes")

        # Search for login API patterns
        login_apis = re.findall(r"""["']([^"']*(?:[Ll]ogin|[Aa]uth)[^"']*apis[^"']*)["']""", js)
        api_login = re.findall(r"""["']([^"']*apis[^"']*(?:[Ll]ogin|[Aa]uth)[^"']*)["']""", js)

        login_combined = set(login_apis + api_login)
        for match in sorted(login_combined)[:20]:
            if len(match) > 3 and "/" in match:
                print(f"    {match}")
    except Exception as e:
        print(f"  Error: {e}")
