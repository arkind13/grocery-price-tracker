"""Complete Auth0 login via Scrape.do session + direct Auth0 API.

Scrape.do maintains session cookies. We extract the state from the resolved
URL, then POST directly to Auth0's /co/authenticate and /u/login/password
APIs through the same Scrape.do session. Bypasses the broken JS widget.

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
SID = f"wool_auth_{int(time.time())}"


def scrapedo(url, **extra):
    """Generic Scrape.do request with session persistence."""
    params = {
        "token": KEY, "url": url, "render": "true",
        "super": "true", "country": "au", "session": SID, "wait": "10000",
    }
    params.update(extra)
    r = requests.get("https://api.scrape.do", params=params, timeout=120)
    return r


def scrapedo_post(url, payload, content_type="application/x-www-form-urlencoded"):
    """POST through Scrape.do."""
    if content_type == "application/x-www-form-urlencoded":
        body = urlencode(payload)
    else:
        body = json.dumps(payload)

    params = {
        "token": KEY, "url": url, "render": "true",
        "super": "true", "country": "au", "session": SID, "wait": "10000",
        "method": "POST",
        "payload": body,
        "headers": json.dumps({
            "Content-Type": content_type,
            "Accept": "application/json, text/html, */*",
            "Origin": "https://auth.woolworths.com.au",
            "Referer": "https://auth.woolworths.com.au/",
            "X-Requested-With": "XMLHttpRequest",
        }),
    }
    r = requests.get("https://api.scrape.do", params=params, timeout=120)
    return r


# ============================================================================
# Step 1: Get Auth0 page + extract state from resolved URL
# ============================================================================
print("=" * 60)
print("STEP 1: Get Auth0 page + extract state")
print("=" * 60)

r1 = scrapedo("https://www.woolworths.com.au/auth/login")
resolved = r1.headers.get("scrape.do-resolved-url", "")
print(f"Resolved URL: {resolved[:120]}...")

state = parse_qs(urlparse(resolved).query).get("state", [None])[0]
if not state:
    print("FAIL: No state in resolved URL")
    sys.exit(1)
print(f"State: {state[:50]}...")

# ============================================================================
# Step 2: POST email to Auth0 identifier
# ============================================================================
print("\n" + "=" * 60)
print("STEP 2: POST email to Auth0")
print("=" * 60)

r2 = scrapedo_post(
    "https://auth.woolworths.com.au/u/login/identifier",
    {"identifier": USER, "state": state, "action": "default"},
)
print(f"HTTP {r2.status_code}, {len(r2.text)} bytes")
print(f"Resolved: {r2.headers.get('scrape.do-resolved-url', '?')[:120]}")

# Check response
resp_text = r2.text
if "password" in resp_text.lower() or "login/password" in resp_text.lower():
    print("-> Proceeding to password step")
elif "mfa" in resp_text.lower():
    print("-> MFA required!")
elif "error" in resp_text.lower():
    error = re.search(r'"message"\s*:\s*"([^"]+)"', resp_text)
    print(f"-> Error: {error.group(1) if error else resp_text[:300]}")
else:
    print(f"Response: {resp_text[:300]}")

# ============================================================================
# Step 3: POST password to Auth0
# ============================================================================
print("\n" + "=" * 60)
print("STEP 3: POST password to Auth0")
print("=" * 60)

r3 = scrapedo_post(
    "https://auth.woolworths.com.au/u/login/password",
    {"password": PASS, "state": state, "action": "default"},
)
print(f"HTTP {r3.status_code}, {len(r3.text)} bytes")
print(f"Resolved: {r3.headers.get('scrape.do-resolved-url', '?')[:200]}")

# Check if we got redirected back to Woolworths
resolved3 = r3.headers.get("scrape.do-resolved-url", "")
if "woolworths.com.au/callback" in resolved3:
    print("-> Callback received!")
elif "woolworths.com.au" in resolved3:
    print("-> Back on Woolworths!")
elif "mfa" in r3.text.lower() or "mfa" in resolved3.lower():
    print("-> MFA required!")
elif "error" in r3.text.lower():
    error = re.search(r'"message"\s*:\s*"([^"]+)"', r3.text)
    print(f"-> Error: {error.group(1) if error else r3.text[:300]}")
else:
    print(f"Response snippet: {r3.text[:300]}")

# Save debug HTML
with open(OUTPUT_DIR / "step3_password_response.html", "w", encoding="utf-8") as f:
    f.write(r3.text[:50000])

# ============================================================================
# Step 4: Load Woolworths homepage through same session
# ============================================================================
print("\n" + "=" * 60)
print("STEP 4: Load Woolworths with session cookies")
print("=" * 60)

r4 = scrapedo("https://www.woolworths.com.au/")
print(f"HTTP {r4.status_code}, {len(r4.text)} bytes")
resolved4 = r4.headers.get("scrape.do-resolved-url", "")
print(f"Resolved: {resolved4[:120]}")

# Check if logged in (look for account name, logout link, etc.)
if "My Account" in r4.text or "Logout" in r4.text or "sign out" in r4.text.lower():
    print("-> Appears logged in!")
else:
    # Check if we got redirected to login
    if "login" in resolved4.lower() or "securelogin" in resolved4.lower():
        print("-> Still not authenticated (redirected to login)")
    else:
        print("-> Auth status unclear")

# ============================================================================
# Step 5: Test mylists API
# ============================================================================
print("\n" + "=" * 60)
print("STEP 5: Test mylists API through session")
print("=" * 60)

r5 = scrapedo("https://www.woolworths.com.au/apis/ui/mylists")
print(f"HTTP {r5.status_code}, {len(r5.text)} bytes")

if r5.status_code == 200:
    try:
        data = r5.json()
        lists = data.get("Response", [])
        print(f"Lists: {len(lists)}")
        if lists:
            print("SUCCESS!")
            for lst in lists:
                name = lst.get("Name", "?")
                lid = lst.get("ListId", "?")
                count = lst.get("ItemCount", "?")
                print(f"  [{lid}] \"{name}\" ({count} items)")

            # Save list data
            with open(OUTPUT_DIR / "mylists_response.json", "w") as f:
                json.dump(data, f, indent=2)
            print(f"Saved: {OUTPUT_DIR / 'mylists_response.json'}")
        else:
            print("No lists — not authenticated")
    except Exception as e:
        print(f"Parse error: {e}")
        print(f"Response: {r5.text[:300]}")
else:
    print(f"Failed: {r5.text[:300]}")

# ============================================================================
# Step 6: Try to extract actual cookies for local use
# ============================================================================
print("\n" + "=" * 60)
print("STEP 6: Extract cookies for local use")
print("=" * 60)

# Scrape.do maintains session cookies server-side
# We can't directly get the cookie string, but we can test if
# the session works for API calls
print("Scrape.do session ID:", SID)
print("Note: Cookies are server-side on Scrape.do's proxy")
print("To use locally, we'd need to extract them from a response header")
