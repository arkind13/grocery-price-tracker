"""Scrape.do POST — correct format: POST to api.scrape.do with target in query."""
import json, os, re, sys, time
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs, quote

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_WORKSPACE = _REPO_ROOT.parent
OUTPUT_DIR = _REPO_ROOT / "data" / "diagnostics"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def _load_env():
    from dotenv import load_dotenv
    load_dotenv(_WORKSPACE / ".env", override=True)

_load_env()

import requests

KEY = os.getenv("SCRAPEDO_API_KEY", "")
USER = os.getenv("WOOLWORTHS_USER", "")
PASS = os.getenv("WOOLWORTHS_PASS", "")
SID = f"wool_post_{int(time.time())}"


def scrapedo_get(url):
    """GET through Scrape.do."""
    return requests.get("https://api.scrape.do", params={
        "token": KEY, "url": url, "render": "true",
        "super": "true", "country": "au", "session": SID, "wait": "10000",
    }, timeout=120)


def scrapedo_post(target_url, form_data):
    """POST through Scrape.do: query params for config, body for form data."""
    params = {
        "token": KEY,
        "url": target_url,  # Scrape.do forwards body to this URL
        "render": "true",
        "super": "true",
        "country": "au",
        "session": SID,
        "wait": "10000",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/html, */*",
        "Origin": "https://auth.woolworths.com.au",
        "Referer": "https://auth.woolworths.com.au/",
        "X-Requested-With": "XMLHttpRequest",
    }
    return requests.post(
        "https://api.scrape.do",
        params=params,
        headers=headers,
        data=urlencode(form_data),
        timeout=120,
    )


# ============================================================================
# Step 1: Get Auth0 state
# ============================================================================
print("=" * 60)
print("STEP 1: Get Auth0 state")
print("=" * 60)

r1 = scrapedo_get("https://www.woolworths.com.au/auth/login")
resolved = r1.headers.get("scrape.do-resolved-url", "")
state = parse_qs(urlparse(resolved).query).get("state", [None])[0]
print(f"State: {state[:50]}..." if state else "FAIL")
if not state: sys.exit(1)

# ============================================================================
# Step 2: POST email
# ============================================================================
print("\n" + "=" * 60)
print("STEP 2: POST email via Scrape.do")
print("=" * 60)

r2 = scrapedo_post(
    "https://auth.woolworths.com.au/u/login/identifier",
    {"identifier": USER, "state": state, "action": "default"},
)
print(f"HTTP {r2.status_code}, {len(r2.text)} bytes")
resolved2 = r2.headers.get("scrape.do-resolved-url", "")
print(f"Resolved: {resolved2[:150] if resolved2 else 'N/A'}")
print(f"Response: {r2.text[:400]}")

# ============================================================================
# Step 3: If identifier accepted, POST password
# ============================================================================
print("\n" + "=" * 60)
print("STEP 3: POST password via Scrape.do")
print("=" * 60)

r3 = scrapedo_post(
    "https://auth.woolworths.com.au/u/login/password",
    {"password": PASS, "state": state, "action": "default"},
)
print(f"HTTP {r3.status_code}, {len(r3.text)} bytes")
resolved3 = r3.headers.get("scrape.do-resolved-url", "")
print(f"Resolved: {resolved3[:200] if resolved3 else 'N/A'}")

if "woolworths.com.au/callback" in (resolved3 or ""):
    print("-> Callback received!")
elif "mfa" in r3.text.lower() or "mfa" in (resolved3 or "").lower():
    print("-> MFA required!")
elif "error" in r3.text.lower():
    print(f"Response: {r3.text[:300]}")
else:
    print(f"Response: {r3.text[:300]}")

# ============================================================================
# Step 4: Test mylists API
# ============================================================================
print("\n" + "=" * 60)
print("STEP 4: Test mylists API")
print("=" * 60)

r4 = scrapedo_get("https://www.woolworths.com.au/apis/ui/mylists")
print(f"HTTP {r4.status_code}")

json_match = re.search(r"<pre>(.*?)</pre>", r4.text)
if json_match:
    data = json.loads(json_match.group(1))
    lists = data.get("Response", [])
    print(f"Lists: {len(lists)}")
    for lst in lists:
        print(f"  [{lst.get('ListId')}] \"{lst.get('Name')}\" ({lst.get('ItemCount','?')} items)")
    if lists:
        with open(OUTPUT_DIR / "mylists_success.json", "w") as f:
            json.dump(data, f, indent=2)
        print("SUCCESS! Lists saved.")
else:
    print(f"Response: {r4.text[:300]}")

print("\nDONE")
