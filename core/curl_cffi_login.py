"""Phase 9.0.b — curl_cffi Login: Find real endpoint.

curl_cffi successfully reaches Woolworths (HTTP 200). This script:
1. Loads the login page and extracts the login API endpoint from JS
2. Tries login with the actual endpoint
3. Extracts and tests the fresh cookie
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_WORKSPACE = _REPO_ROOT.parent
OUTPUT_DIR = _REPO_ROOT / "data" / "diagnostics"
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

from curl_cffi import requests as cffi_requests


def _cookies_to_str(cookies) -> str:
    """Convert curl_cffi cookies to a cookie header string."""
    parts = []
    if hasattr(cookies, 'items'):
        for name, val in cookies.items():
            parts.append(f"{name}={val}")
    else:
        for c in cookies:
            if hasattr(c, 'name'):
                parts.append(f"{c.name}={c.value}")
            elif isinstance(c, tuple):
                parts.append(f"{c[0]}={c[1]}")
            elif isinstance(c, str):
                if "=" in c:
                    parts.append(c)
    return "; ".join(parts)


def extract_login_endpoint(session):
    """Load login page and extract the actual login API endpoint from JS."""
    print("=" * 60)
    print("STEP 1: Finding Login API Endpoint")
    print("=" * 60)

    r = session.get(
        "https://www.woolworths.com.au/shop/login",
        impersonate="chrome131",
        timeout=30,
    )
    print(f"  HTTP {r.status_code}, {len(r.text)} bytes")

    js_text = r.text

    # Search for Login-related API endpoints in the JS
    # Woolworths Angular app likely has /apis/ui/... login patterns
    patterns = [
        # Direct API endpoint references
        r'(/apis/ui/[A-Za-z]+/Login)',
        r'(/apis/ui/[^"\')\s]+login[^"\')\s]*)',
        r'(/apis/ui/[^"\')\s]+Login[^"\')\s]*)',
        # Look for "Login" in route definitions
        r'["\']((?:/apis/ui/)?[^"\']*Login[^"\']*)["\']',
        # Checkout API patterns
        r'(/apis/ui/Checkout[^"\')\s]*)',
        # MyAccount patterns
        r'(/apis/ui/MyAccount[^"\')\s]*)',
        # Auth patterns
        r'(/apis/ui/[^"\')\s]*[Aa]uth[^"\')\s]*)',
    ]

    found_endpoints = set()
    for pat in patterns:
        matches = re.findall(pat, js_text, re.IGNORECASE)
        for m in matches:
            if isinstance(m, tuple):
                m = m[0]
            if m not in found_endpoints and len(m) > 5:
                found_endpoints.add(m)

    print(f"  Potential login endpoints ({len(found_endpoints)}):")
    for ep in sorted(found_endpoints):
        print(f"    {ep}")

    # Also look for the full login request body structure
    body_patterns = re.findall(
        r'(?:loginRequest|LoginRequest|login_request)\s*[=:]\s*(\{[^}]+\})',
        js_text, re.IGNORECASE
    )
    if body_patterns:
        print(f"\n  Login request body patterns:")
        for bp in body_patterns[:5]:
            print(f"    {bp[:200]}")

    return list(found_endpoints)


def try_login_endpoints(session, endpoints):
    """Try each login endpoint with the credentials."""
    print("\n" + "=" * 60)
    print("STEP 2: Trying Login Endpoints")
    print("=" * 60)

    username = os.getenv("WOOLWORTHS_USER", "")
    password = os.getenv("WOOLWORTHS_PASS", "")

    if not username or not password:
        print("  [SKIP] No credentials")
        return None

    payload_variants = [
        {"email": username, "password": password},
        {"Email": username, "Password": password},
        {"loginEmail": username, "loginPassword": password},
        {"username": username, "password": password},
        {"Username": username, "Password": password},
        {"email": username, "password": password, "RememberMe": False},
    ]

    for endpoint in endpoints:
        # Ensure it's a full URL
        if endpoint.startswith("/"):
            url = f"https://www.woolworths.com.au{endpoint}"
        elif endpoint.startswith("http"):
            url = endpoint
        else:
            url = f"https://www.woolworths.com.au/{endpoint}"

        for payload in payload_variants:
            try:
                r = session.post(
                    url,
                    json=payload,
                    impersonate="chrome131",
                    timeout=30,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Origin": "https://www.woolworths.com.au",
                        "Referer": "https://www.woolworths.com.au/shop/login",
                    },
                )
                status = r.status_code
                resp_len = len(r.text)

                if status == 200:
                    print(f"\n  [200] {url} — SUCCESS!")
                    print(f"  Response: {r.text[:300]}")
                    cookie = _cookies_to_str(session.cookies)
                    print(f"  Cookie length: {len(cookie)}")
                    return cookie
                elif status == 400:
                    print(f"  [400] {url} — {r.text[:100]}")
                elif status == 401:
                    print(f"  [401] {url} — bad credentials: {r.text[:100]}")
                elif status == 403:
                    print(f"  [403] {url} — blocked")
                elif status == 302 or status == 301:
                    print(f"  [{status}] {url} — redirect to {r.headers.get('Location', '?')}")
                elif status == 429:
                    print(f"  [429] {url} — rate limited")
                else:
                    print(f"  [{status}] {url} ({resp_len}B): {r.text[:120]}")
            except Exception as exc:
                print(f"  [ERR] {url} — {exc}")

    return None


def test_api(cookie_str):
    """Test cookie against mylists API."""
    print("\n" + "=" * 60)
    print("STEP 3: Testing Cookie Against Mylists API")
    print("=" * 60)

    r = cffi_requests.get(
        "https://www.woolworths.com.au/apis/ui/mylists",
        headers={
            "Accept": "application/json",
            "Accept-Language": "en-AU,en;q=0.9",
            "Referer": "https://www.woolworths.com.au/shop/mylists",
            "Origin": "https://www.woolworths.com.au",
            "Cookie": cookie_str,
        },
        impersonate="chrome131",
        timeout=30,
    )
    print(f"  HTTP {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        lists = data.get("Response", [])
        print(f"  [SUCCESS] {len(lists)} lists found:")
        for lst in lists:
            name = lst.get("Name", "?")
            lid = lst.get("ListId", "?")
            count = lst.get("ItemCount", "?")
            print(f"    [{lid}] \"{name}\" ({count} items)")
        return True, data
    else:
        print(f"  Failed: {r.text[:300]}")
        return False, None


def main():
    print("curl_cffi WOOLWORTHS LOGIN — FINDING REAL ENDPOINT")
    print("=" * 60)

    session = cffi_requests.Session()

    # Step 1: Find endpoints
    endpoints = extract_login_endpoint(session)

    # Step 2: Try logins
    cookie = try_login_endpoints(session, endpoints)

    # Step 3: Test
    if cookie:
        success, data = test_api(cookie)
        if success:
            cookie_path = OUTPUT_DIR / "fresh_wool_cookie.txt"
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(cookie)
            print(f"\n  Cookie saved: {cookie_path}")
            return 0

    print("\n[FAIL] Could not obtain working cookie")
    return 1


if __name__ == "__main__":
    sys.exit(main())
