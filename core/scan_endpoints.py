"""Quick endpoint scan of Woolworths login page JS."""
import re, sys
from curl_cffi import requests as r

s = r.Session()
resp = s.get("https://www.woolworths.com.au/shop/login", impersonate="chrome131", timeout=30)
html = resp.text
print(f"Page size: {len(html)} bytes")

# Find all API route segments
api_routes = re.findall(r"(/apis/ui/[A-Za-z]+)", html)
print(f"\nAPI route segments ({len(set(api_routes))} unique):")
for route in sorted(set(api_routes)):
    print(f"  {route}")

# Find login-related API references
login_refs = re.findall(r"[\"']([^\"']*login[^\"']*)[\"']", html, re.IGNORECASE)
print(f"\nLogin references ({len(login_refs)}):")
for ref in sorted(set(login_refs))[:30]:
    print(f"  {ref}")

# Search for the actual login form submission
# Woolworths Angular login form likely has a specific API call
form_actions = re.findall(r"action\s*=\s*[\"']([^\"']+)[\"']", html, re.IGNORECASE)
print(f"\nForm actions: {form_actions}")

# Look for the Login API endpoint in the JS
# Common Woolworths patterns
known = [
    "/apis/ui/Login/Login",
    "/apis/ui/CheckoutApi/Login",
    "/apis/ui/MyAccount/Login",
    "/apis/ui/login",
    "/apis/ui/Login",
]
print("\nProbing known endpoints:")
for ep in known:
    try:
        r2 = r.get(
            f"https://www.woolworths.com.au{ep}",
            impersonate="chrome131",
            timeout=15,
        )
        print(f"  GET {ep}: HTTP {r2.status_code} ({len(r2.text)}B)")
    except Exception as e:
        print(f"  GET {ep}: ERROR {e}")
