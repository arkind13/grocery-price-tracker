"""Try Woolworths login with form-encoded POST and curl_cffi impersonation."""
import os, sys, re
from pathlib import Path

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

print(f"User: {'set' if user else 'MISSING'} ({len(user)} chars)")
print(f"Pass: {'set' if pw else 'MISSING'} ({len(pw)} chars)")

session = r.Session()

# Step 1: Get login page to extract CSRF / build session
print("\n[1] Getting login page...")
resp = session.get(
    "https://www.woolworths.com.au/shop/login",
    impersonate="chrome131",
    timeout=30,
)
print(f"  HTTP {resp.status_code}, {len(resp.text)} bytes")

# Look for hidden form fields / CSRF
hidden = re.findall(r'<input[^>]*type=["\']hidden["\'][^>]*>', resp.text)
print(f"  Hidden inputs: {len(hidden)}")
for h in hidden:
    name = re.search(r'name=["\']([^"\']+)["\']', h)
    val = re.search(r'value=["\']([^"\']*)["\']', h)
    if name:
        print(f"    {name.group(1)} = {val.group(1) if val else ''}")

# Step 2: Try POST to /shop/login with form data
print("\n[2] POST to /shop/login (form-encoded)...")
try:
    r2 = session.post(
        "https://www.woolworths.com.au/shop/login",
        data={"email": user, "password": pw},
        impersonate="chrome131",
        timeout=30,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.woolworths.com.au",
            "Referer": "https://www.woolworths.com.au/shop/login",
        },
    )
    print(f"  HTTP {r2.status_code}, {len(r2.text)} bytes")
    print(f"  URL: {r2.url}")
    print(f"  Title: {r2.text[:500]}")
except Exception as e:
    print(f"  Error: {e}")

# Step 3: Try POST to /apis/ui/login with JSON
print("\n[3] POST to /apis/ui/login (JSON)...")
try:
    r3 = session.post(
        "https://www.woolworths.com.au/apis/ui/login",
        json={"email": user, "password": pw, "IsDelivery": False},
        impersonate="chrome131",
        timeout=30,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.woolworths.com.au",
            "Referer": "https://www.woolworths.com.au/shop/login",
        },
    )
    print(f"  HTTP {r3.status_code}, {len(r3.text)} bytes")
    print(f"  Response: {r3.text[:300]}")
except Exception as e:
    print(f"  Error: {e}")

# Step 4: Try POST to /apis/ui/Login with JSON (case variant)
print("\n[4] POST to /apis/ui/Login (JSON)...")
try:
    r4 = session.post(
        "https://www.woolworths.com.au/apis/ui/Login",
        json={"Email": user, "Password": pw},
        impersonate="chrome131",
        timeout=30,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.woolworths.com.au",
            "Referer": "https://www.woolworths.com.au/shop/login",
        },
    )
    print(f"  HTTP {r4.status_code}, {len(r4.text)} bytes")
    print(f"  Response: {r4.text[:300]}")
except Exception as e:
    print(f"  Error: {e}")

# Step 5: Try the /apis/ui/Bootstrap first (sometimes needed for auth)
print("\n[5] GET /apis/ui/Bootstrap (session init)...")
try:
    r5 = session.get(
        "https://www.woolworths.com.au/apis/ui/Bootstrap",
        impersonate="chrome131",
        timeout=30,
        headers={
            "Accept": "application/json",
            "Referer": "https://www.woolworths.com.au/",
        },
    )
    print(f"  HTTP {r5.status_code}, {len(r5.text)} bytes")
    print(f"  Response: {r5.text[:300]}")
except Exception as e:
    print(f"  Error: {e}")

# Print final session cookies
cookies = session.cookies
cookie_str = "; ".join(
    f"{getattr(c, 'name', '')}={getattr(c, 'value', '')}"
    for c in cookies if hasattr(c, 'name')
)
if not cookie_str and hasattr(cookies, 'items'):
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
print(f"\nFinal cookies ({len(cookies)}): {len(cookie_str)} chars")
