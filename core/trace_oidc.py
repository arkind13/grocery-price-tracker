"""Trace Woolworths OIDC login flow and attempt authentication."""
import os, sys, re, json
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs

_SCRIPT_DIR = Path(__file__).resolve().parent
_WORKSPACE = _SCRIPT_DIR.parent.parent

def _load_env():
    try:
        from dotenv import load_dotenv
        env_path = _WORKSPACE / ".env"
        if env_path.is_file():
            load_dotenv(dotenv_path=str(env_path), override=True)
            return
    except ImportError:
        pass
    env_path = _WORKSPACE / ".env"
    if env_path.is_file():
        with open(env_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                os.environ[key] = val

_load_env()

from curl_cffi import requests as r

user = os.getenv("WOOLWORTHS_USER", "")
pw = os.getenv("WOOLWORTHS_PASS", "")

session = r.Session()

# Step 1: Access the secure login URL
print("=" * 60)
print("STEP 1: Access /shop/securelogin")
print("=" * 60)
resp = session.get(
    "https://www.woolworths.com.au/shop/securelogin",
    impersonate="chrome131",
    timeout=30,
    headers={
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
    },
)
print(f"HTTP {resp.status_code}, {len(resp.text)} bytes")
print(f"Final URL: {resp.url}")

# Step 2: Follow the redirect to /auth/login
print("\n" + "=" * 60)
print("STEP 2: Access /auth/login")
print("=" * 60)
resp2 = session.get(
    "https://www.woolworths.com.au/auth/login",
    impersonate="chrome131",
    timeout=30,
    headers={
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
    },
    allow_redirects=True,
)
print(f"HTTP {resp2.status_code}, {len(resp2.text)} bytes")
print(f"Final URL: {resp2.url}")

# Check for redirects
if resp2.history:
    print(f"Redirects: {len(resp2.history)}")
    for h in resp2.history:
        print(f"  {h.status_code} -> {h.url[:120]}")

# Parse the page for form / login
html = resp2.text
print(f"\nPage title: {re.search(r'<title>([^<]+)</title>', html)}")

# Look for form action
forms = re.findall(r'<form[^>]*action=["\']([^"\']+)["\']', html)
print(f"Forms: {forms}")

# Look for any redirect URLs in the page
redirects = re.findall(r'(?:redirect|return|continue|next)[^=]*=["\']([^"\']+)["\']', html)
print(f"Redirect params: {redirects[:5]}")

# Step 3: Try the full OIDC flow with the redirect_uri from settings
print("\n" + "=" * 60)
print("STEP 3: OIDC Auth Flow")
print("=" * 60)
auth_url = (
    "https://www.woolworths.com.au/auth/login"
    "?redirect_uri=https://www.woolworths.com.au/callback"
    "&path=/#postSuccessLogin"
)
print(f"Auth URL: {auth_url}")
resp3 = session.get(auth_url, impersonate="chrome131", timeout=30)
print(f"HTTP {resp3.status_code}, final URL: {resp3.url}")
if resp3.history:
    for h in resp3.history:
        print(f"  -> {h.status_code} {h.url[:150]}")

# Check if we're at an identity provider
domain = urlparse(resp3.url).netloc
print(f"Current domain: {domain}")
print(f"Page size: {len(resp3.text)} bytes")
print(f"Title: {re.search(r'<title>([^<]+)</title>', resp3.text)}")

# If at identity provider, look for login form
idp_forms = re.findall(r'<form[^>]*action=["\']([^"\']+)["\']', resp3.text)
print(f"IDP forms: {idp_forms}")

# Look for username/password fields
inputs = re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*>', resp3.text)
print(f"Input names: {inputs[:10]}")

# Save HTML for analysis
out = _SCRIPT_DIR.parent / "data" / "diagnostics" / "auth_login_page.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(resp3.text[:100000])
print(f"\nHTML saved: {out}")
