"""Complete Auth0 login via Scrape.do POST proxying.

Scrape.do supports POST by sending a POST request to their API with the
target URL in headers/body. Uses session persistence across requests.

Never prints secrets.
"""
import json, os, re, sys, time
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

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
SID = f"wool_pw_{int(time.time())}"


def scrapedo_get(url):
    """GET through Scrape.do with session persistence."""
    return requests.get("https://api.scrape.do", params={
        "token": KEY, "url": url, "render": "true",
        "super": "true", "country": "au", "session": SID, "wait": "10000",
    }, timeout=120)


def scrapedo_post(target_url, form_data):
    """POST through Scrape.do by sending POST to their API."""
    # Scrape.do POST: send POST request to api.scrape.do with target in header
    headers = {
        "x-scrape-do-url": target_url,
        "x-scrape-do-token": KEY,
        "x-scrape-do-render": "true",
        "x-scrape-do-super": "true",
        "x-scrape-do-country": "au",
        "x-scrape-do-session": SID,
        "x-scrape-do-wait": "10000",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/html, */*",
        "Origin": "https://auth.woolworths.com.au",
        "Referer": "https://auth.woolworths.com.au/",
        "X-Requested-With": "XMLHttpRequest",
    }
    return requests.post(
        "https://api.scrape.do",
        headers=headers,
        data=urlencode(form_data),
        timeout=120,
    )


def scrapedo_post_json(target_url, json_data):
    """POST JSON through Scrape.do."""
    headers = {
        "x-scrape-do-url": target_url,
        "x-scrape-do-token": KEY,
        "x-scrape-do-render": "true",
        "x-scrape-do-super": "true",
        "x-scrape-do-country": "au",
        "x-scrape-do-session": SID,
        "x-scrape-do-wait": "10000",
        "Content-Type": "application/json",
        "Accept": "application/json, text/html, */*",
        "Origin": "https://auth.woolworths.com.au",
        "Referer": "https://auth.woolworths.com.au/",
        "X-Requested-With": "XMLHttpRequest",
    }
    return requests.post(
        "https://api.scrape.do",
        headers=headers,
        json=json_data,
        timeout=120,
    )


# ============================================================================
# Step 1: Get Auth0 page + extract state
# ============================================================================
print("=" * 60)
print("STEP 1: Get Auth0 page + state")
print("=" * 60)

r1 = scrapedo_get("https://www.woolworths.com.au/auth/login")
resolved = r1.headers.get("scrape.do-resolved-url", "")
state = parse_qs(urlparse(resolved).query).get("state", [None])[0]
print(f"State: {state[:50]}..." if state else "FAIL: no state")
if not state:
    sys.exit(1)

# ============================================================================
# Step 2: POST email (form-encoded)
# ============================================================================
print("\n" + "=" * 60)
print("STEP 2: POST email (form-encoded)")
print("=" * 60)

r2 = scrapedo_post(
    "https://auth.woolworths.com.au/u/login/identifier",
    {"identifier": USER, "state": state, "action": "default"},
)
print(f"HTTP {r2.status_code}, {len(r2.text)} bytes")
resolved2 = r2.headers.get("scrape.do-resolved-url", "")
print(f"Resolved: {resolved2[:150] if resolved2 else 'N/A'}")

resp2 = r2.text[:500]
if "password" in resp2.lower():
    print("-> Password step available")
elif "mfa" in resp2.lower():
    print("-> MFA required!")
elif "error" in resp2.lower():
    print(f"-> Error: {resp2[:200]}")
else:
    print(f"Response: {resp2}")

# ============================================================================
# Step 3: POST email (JSON) — try alternate format
# ============================================================================
print("\n" + "=" * 60)
print("STEP 3: POST email (JSON format)")
print("=" * 60)

r3 = scrapedo_post_json(
    "https://auth.woolworths.com.au/u/login/identifier",
    {"identifier": USER, "state": state, "action": "default"},
)
print(f"HTTP {r3.status_code}, {len(r3.text)} bytes")
resolved3 = r3.headers.get("scrape.do-resolved-url", "")
print(f"Resolved: {resolved3[:150] if resolved3 else 'N/A'}")

resp3 = r3.text[:500]
if "password" in resp3.lower():
    print("-> Password step available!")
elif "mfa" in resp3.lower():
    print("-> MFA required!")
elif "error" in resp3.lower():
    print(f"-> Error: {resp3[:200]}")
else:
    print(f"Response: {resp3}")

# Save responses for debugging
with open(OUTPUT_DIR / "scrapedo_post_resp.html", "w", encoding="utf-8") as f:
    f.write(r3.text[:50000])

# ============================================================================
# Step 4: If password step reached, POST password
# ============================================================================
if "password" in resp3.lower():
    print("\n" + "=" * 60)
    print("STEP 4: POST password (JSON)")
    print("=" * 60)

    r4 = scrapedo_post_json(
        "https://auth.woolworths.com.au/u/login/password",
        {"password": PASS, "state": state, "action": "default"},
    )
    print(f"HTTP {r4.status_code}, {len(r4.text)} bytes")
    resolved4 = r4.headers.get("scrape.do-resolved-url", "")
    print(f"Resolved: {resolved4[:200] if resolved4 else 'N/A'}")

    if "woolworths.com.au" in resolved4.lower():
        print("-> Redirected to Woolworths!")
    elif "mfa" in r4.text.lower() or "mfa" in resolved4.lower():
        print("-> MFA required!")
    else:
        print(f"Response: {r4.text[:300]}")

    # Test API
    print("\n  Testing mylists API...")
    r5 = scrapedo_get("https://www.woolworths.com.au/apis/ui/mylists")
    print(f"  HTTP {r5.status_code}")
    if r5.status_code == 200:
        # Parse JSON from HTML wrapper
        json_match = re.search(r'<pre>(.*?)</pre>', r5.text)
        if json_match:
            data = json.loads(json_match.group(1))
            lists = data.get("Response", [])
            print(f"  Lists: {len(lists)}")
            for lst in lists:
                print(f"    [{lst.get('ListId')}] \"{lst.get('Name')}\" ({lst.get('ItemCount','?')} items)")
            if lists:
                with open(OUTPUT_DIR / "mylists_success.json", "w") as f:
                    json.dump(data, f, indent=2)
                print("  SUCCESS! Lists found and saved.")
        else:
            print(f"  Response: {r5.text[:300]}")
    else:
        print(f"  Failed: {r5.text[:200]}")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
