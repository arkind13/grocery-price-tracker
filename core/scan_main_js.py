"""Scan the main Angular JS bundle for login API endpoints."""
import re, sys
from curl_cffi import requests as r

MAIN_JS = "https://cdn0.woolworths.media/wowssr/syd2/a10/browser/main.fa70e0ae97263e86.js"

print(f"Fetching main.js...")
resp = r.get(MAIN_JS, impersonate="chrome131", timeout=60)
js = resp.text
print(f"Size: {len(js)} bytes ({len(js)/1024:.0f} KB)")

# Search for login-related strings near "apis"
print("\n=== Login + API patterns ===")
patterns = re.findall(r".{0,30}(?:login|Login|LOGIN).{0,30}(?:apis|/api).{0,30}", js)
for p in list(set(patterns))[:30]:
    print(f"  {p.strip()}")

print("\n=== API route definitions ===")
routes = re.findall(r"""["']/apis/ui/[A-Za-z/]+["']""", js)
unique_routes = sorted(set(routes))
for route in unique_routes:
    print(f"  {route}")

print("\n=== Login/Auth in API context ===")
auth_apis = re.findall(r"""["']/apis/ui/(?:[A-Za-z]+/)?(?:[Ll]ogin|[Aa]uth|[Ss]ign[Ii]n|[Tt]oken)[^"']*["']""", js)
for api in sorted(set(auth_apis)):
    print(f"  {api}")

# Also search for POST requests with login
print("\n=== Login POST patterns ===")
post_login = re.findall(r""".{0,40}post.{0,10}(?:login|Login|LOGIN).{0,40}""", js)
for p in set(post_login)[:20]:
    print(f"  {p.strip()}")

# Look for CheckoutApi references
print("\n=== CheckoutApi references ===")
checkout = re.findall(r"""["']/apis/ui/Checkout[^"']*["']""", js)
for c in sorted(set(checkout)):
    print(f"  {c}")
