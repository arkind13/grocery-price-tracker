"""Auth0 cross-origin authentication API flow.

The Auth0 universal login JS widget calls the /co/authenticate API.
This script uses that API directly to authenticate and get session tokens.
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
# Step 1: Get Auth0 page and extract state + client ID
# =========================================================================
print("=" * 60)
print("STEP 1: Get Auth0 config")
print("=" * 60)

resp = session.get(
    "https://www.woolworths.com.au/auth/login",
    impersonate="chrome131",
    timeout=30,
    allow_redirects=True,
)
parsed = urlparse(resp.url)
state = parse_qs(parsed.query).get("state", [None])[0]
print(f"State: {state[:40]}...")

# Extract client ID from authorize URL in history
client_id = "igXwVdjlyvwv8FFWDKcnBOO9hXU3cr2U"  # Known from earlier tests
print(f"Client ID: {client_id}")

# Get Auth0 tenant config
try:
    config_resp = r.get(
        f"https://auth.woolworths.com.au/client/{client_id}.js",
        impersonate="chrome131",
        timeout=15,
    )
    print(f"Client JS: HTTP {config_resp.status_code}")
except:
    pass

# =========================================================================
# Step 2: Use Auth0 /co/authenticate API
# =========================================================================
print("\n" + "=" * 60)
print("STEP 2: Auth0 /co/authenticate")
print("=" * 60)

# The Auth0 cross-origin authentication flow:
# POST to /co/authenticate with grant_type=password

auth0_tenant = "auth.woolworths.com.au"
realm = "wow-auth"  # Woolworths connection name

# Try the Resource Owner Password Grant
auth_payload = {
    "client_id": client_id,
    "username": user,
    "password": pw,
    "realm": realm,
    "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
    "scope": "openid profile email offline_access",
}

try:
    auth_resp = session.post(
        f"https://{auth0_tenant}/co/authenticate",
        json=auth_payload,
        impersonate="chrome131",
        timeout=30,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": f"https://{auth0_tenant}",
            "Auth0-Client": base64.b64encode(json.dumps({
                "name": "auth0.js",
                "version": "9.27.0",
            }).encode()).decode(),
        },
    )
    print(f"HTTP {auth_resp.status_code}, {len(auth_resp.text)} bytes")
    
    if auth_resp.status_code == 200:
        data = auth_resp.json()
        print("SUCCESS! Auth response:")
        for key in data:
            val = data[key]
            if isinstance(val, str) and len(val) > 40:
                val = val[:40] + "..."
            print(f"  {key}: {val}")
        
        # Check for MFA
        if "mfa_required" in auth_resp.text or "mfa" in str(data).lower():
            print("\n  MFA REQUIRED — need to handle 2FA")
            
    elif auth_resp.status_code == 403:
        print(f"Auth rejected: {auth_resp.text[:300]}")
    elif auth_resp.status_code == 429:
        print("Rate limited")
    else:
        print(f"Response: {auth_resp.text[:500]}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# =========================================================================
# Step 3: Try with different realm/connection names
# =========================================================================
print("\n" + "=" * 60)
print("STEP 3: Try different connection names")
print("=" * 60)

connections = [
    "wow-auth",
    "Woolworths",
    "woolworths",
    "Username-Password-Authentication",
    "Woolworths-Auth",
    "everyday-rewards",
]

for conn in connections:
    auth_payload["realm"] = conn
    try:
        r2 = session.post(
            f"https://{auth0_tenant}/co/authenticate",
            json=auth_payload,
            impersonate="chrome131",
            timeout=20,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": f"https://{auth0_tenant}",
            },
        )
        resp_text = r2.text[:150]
        if "mfa" in r2.text.lower() or r2.status_code == 200:
            print(f"  realm='{conn}': HTTP {r2.status_code} — {resp_text}")
        elif r2.status_code == 403 and "invalid" in r2.text.lower():
            print(f"  realm='{conn}': HTTP {r2.status_code} — invalid")
        elif r2.status_code == 403:
            print(f"  realm='{conn}': HTTP {r2.status_code} — {resp_text}")
        else:
            print(f"  realm='{conn}': HTTP {r2.status_code} — {resp_text}")
    except Exception as e:
        print(f"  realm='{conn}': Error {e}")

# =========================================================================
# Step 4: Build and test cookies
# =========================================================================
print("\n" + "=" * 60)
print("STEP 4: Test cookies")
print("=" * 60)

cookie_str = "; ".join(
    f"{getattr(c, 'name', '')}={getattr(c, 'value', '')}"
    for c in session.cookies if hasattr(c, 'name')
)
print(f"Cookie length: {len(cookie_str)} chars")

if cookie_str:
    try:
        r4 = r.get(
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
        print(f"API: HTTP {r4.status_code}")
        if r4.status_code == 200:
            data = r4.json()
            lists = data.get("Response", [])
            if lists:
                print(f"SUCCESS! {len(lists)} lists:")
                for lst in lists:
                    print(f"  [{lst.get('ListId')}] \"{lst.get('Name')}\" ({lst.get('ItemCount','?')} items)")
            else:
                print("No lists — auth not complete")
        else:
            print(f"Failed: {r4.text[:200]}")
    except Exception as e:
        print(f"Error: {e}")
