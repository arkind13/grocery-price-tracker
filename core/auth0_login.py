"""Complete Auth0 login flow for Woolworths — fixed version.

Correctly stops at Auth0 page to extract state, then completes the OIDC flow.
"""
import os, sys, re, json, base64
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_SCRIPT_DIR = Path(__file__).resolve().parent
_WORKSPACE = _SCRIPT_DIR.parent.parent
OUTPUT_DIR = _SCRIPT_DIR.parent / "data" / "diagnostics"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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

# =========================================================================
# Step 1: Get Auth0 login page (DO NOT follow redirects from securelogin)
# =========================================================================
print("=" * 60)
print("STEP 1: Navigate to Auth0 login page")
print("=" * 60)

# Go directly to the auth URL
resp = session.get(
    "https://www.woolworths.com.au/auth/login",
    impersonate="chrome131",
    timeout=30,
    allow_redirects=True,  # Follow to Auth0
)
print(f"Final URL: {resp.url}")
print(f"HTTP {resp.status_code}, {len(resp.text)} bytes")

# Extract state from URL
parsed = urlparse(resp.url)
state = parse_qs(parsed.query).get("state", [None])[0]
print(f"State: {state[:60]}..." if state and len(state) > 60 else f"State: {state}")

# Extract universal_login_context from HTML
ctx_match = re.search(
    r"""universal_login_context=JSON\.parse\(.*?atob\("([^"]+)"\)""",
    resp.text
)
ctx = {}
if ctx_match:
    ctx_b64 = ctx_match.group(1)
    ctx_json = base64.b64decode(ctx_b64).decode("utf-8")
    ctx = json.loads(ctx_json)
    print(f"Client: {ctx.get('client', {}).get('name', '?')}")
    print(f"Client ID: {ctx.get('client', {}).get('id', '?')}")

# Extract _csrf token from page
csrf_match = re.search(r'name="_csrf"[^>]*value="([^"]+)"', resp.text)
_csrf = csrf_match.group(1) if csrf_match else ""
print(f"CSRF: {'found' if _csrf else 'NOT FOUND'}")

# Extract transaction ID from page
txn_match = re.search(r'"transactionId":"([^"]+)"', resp.text)
txn_id = txn_match.group(1) if txn_match else ""
print(f"Transaction: {'found' if txn_id else 'NOT FOUND'}")

# =========================================================================
# Step 2: POST email to Auth0 identifier endpoint
# =========================================================================
print("\n" + "=" * 60)
print("STEP 2: POST email identifier")
print("=" * 60)

if not state:
    print("ERROR: No state parameter")
    sys.exit(1)

# Auth0 universal login identifier endpoint
identifier_url = "https://auth.woolworths.com.au/u/login/identifier"
payload = {
    "identifier": user,
    "state": state,
    "action": "default",
}
if txn_id:
    payload["transactionId"] = txn_id

print(f"POST {identifier_url}")
print(f"Payload keys: {list(payload.keys())}")

try:
    resp2 = session.post(
        identifier_url,
        data=payload,  # form-encoded, not JSON
        impersonate="chrome131",
        timeout=30,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/html",
            "Origin": "https://auth.woolworths.com.au",
            "Referer": resp.url,
            "X-Requested-With": "XMLHttpRequest",
            "Auth0-Client": base64.b64encode(json.dumps({
                "name": "auth0.js",
                "version": "9.27.0",
            }).encode()).decode(),
        },
    )
    print(f"HTTP {resp2.status_code}, {len(resp2.text)} bytes")
    print(f"URL: {resp2.url}")
    
    if resp2.status_code == 200:
        try:
            data = resp2.json()
            print(f"Response: {json.dumps(data, indent=2)[:500]}")
        except:
            print(f"Response: {resp2.text[:500]}")
    else:
        print(f"Response: {resp2.text[:300]}")
        
    # Check if we're redirected to password page
    if "login/password" in resp2.url or "password" in resp2.text.lower():
        print("-> Redirected to password page")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# =========================================================================
# Step 3: POST password  
# =========================================================================
print("\n" + "=" * 60)
print("STEP 3: POST password")
print("=" * 60)

password_url = "https://auth.woolworths.com.au/u/login/password"
pwd_payload = {
    "password": pw,
    "state": state,
    "action": "default",
}
if txn_id:
    pwd_payload["transactionId"] = txn_id

try:
    resp3 = session.post(
        password_url,
        data=pwd_payload,
        impersonate="chrome131",
        timeout=30,
        allow_redirects=True,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/html",
            "Origin": "https://auth.woolworths.com.au",
            "Referer": resp2.url if resp2 else resp.url,
            "X-Requested-With": "XMLHttpRequest",
            "Auth0-Client": base64.b64encode(json.dumps({
                "name": "auth0.js",
                "version": "9.27.0",
            }).encode()).decode(),
        },
    )
    print(f"HTTP {resp3.status_code}, {len(resp3.text)} bytes")
    print(f"Final URL: {resp3.url}")
    
    if resp3.history:
        print(f"Redirects ({len(resp3.history)}):")
        for h in resp3.history:
            print(f"  {h.status_code} -> {h.url[:150]}")
    
    # Check if we got back to Woolworths with code
    if "woolworths.com.au" in resp3.url and "code=" in resp3.url:
        print("-> SUCCESS! Authorization code received")
    elif "mfa" in resp3.url.lower() or "mfa" in resp3.text.lower():
        print("-> MFA challenge detected")
    else:
        print(f"Response snippet: {resp3.text[:500]}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# =========================================================================
# Step 4: Extract and test cookies
# =========================================================================
print("\n" + "=" * 60)
print("STEP 4: Test final cookies")
print("=" * 60)

# Build cookie string from session
cookie_str = "; ".join(
    f"{getattr(c, 'name', '')}={getattr(c, 'value', '')}"
    for c in session.cookies if hasattr(c, 'name')
)
print(f"Cookie length: {len(cookie_str)} chars")

if cookie_str:
    try:
        resp4 = r.get(
            "https://www.woolworths.com.au/apis/ui/mylists",
            headers={
                "Accept": "application/json",
                "Referer": "https://www.woolworths.com.au/shop/mylists",
                "Origin": "https://www.woolworths.com.au",
                "Cookie": cookie_str,
            },
            impersonate="chrome131",
            timeout=30,
        )
        print(f"Mylists API: HTTP {resp4.status_code}")
        if resp4.status_code == 200:
            data = resp4.json()
            lists = data.get("Response", [])
            if lists:
                print(f"SUCCESS! {len(lists)} lists found:")
                for lst in lists:
                    name = lst.get("Name", "?")
                    lid = lst.get("ListId", "?")
                    count = lst.get("ItemCount", "?")
                    print(f"  [{lid}] \"{name}\" ({count} items)")
            else:
                print("No lists returned — may need additional auth")
        else:
            print(f"Failed: {resp4.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")
else:
    print("No cookies obtained from login flow")
