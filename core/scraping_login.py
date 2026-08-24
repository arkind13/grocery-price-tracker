"""9.0.b — Fresh Woolworths cookie via Scrape.do / ZenRows.

Both services render JavaScript and maintain session cookies across requests.
This is a 5-step OIDC login flow through Auth0 back to Woolworths.

Flow:
  1. Load /shop/securelogin → Auth0 login page (JS-rendered)
  2. Extract state + CSRF from Auth0 page
  3. POST email to Auth0 /u/login/identifier
  4. POST password to Auth0 /u/login/password
  5. Follow callback → Woolworths → extract cookies
  6. Test cookies against /apis/ui/mylists

Never prints secret values.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse, parse_qs

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

import requests

SCRAPEDO_KEY = os.getenv("SCRAPEDO_API_KEY", "")
ZENROWS_KEY = os.getenv("ZENROWS_API_KEY", "")
WOOL_USER = os.getenv("WOOLWORTHS_USER", "")
WOOL_PASS = os.getenv("WOOLWORTHS_PASS", "")

SESSION_ID = f"wool_phase9_{int(time.time())}"


# ============================================================================
# Scrape.do helpers
# ============================================================================
def scrapedo_get(url: str, extra_params: dict = None) -> requests.Response:
    """GET a URL through Scrape.do with JS rendering and session persistence."""
    params = {
        "token": SCRAPEDO_KEY,
        "url": url,
        "render": "true",
        "super": "true",
        "country": "au",
        "session": SESSION_ID,
        "wait": "8000",
    }
    if extra_params:
        params.update(extra_params)
    return requests.get("https://api.scrape.do", params=params, timeout=120)


def scrapedo_post(url: str, payload: dict, extra_headers: dict = None) -> requests.Response:
    """POST to a URL through Scrape.do with session persistence."""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json, text/html, */*",
        "Origin": "https://auth.woolworths.com.au",
        "Referer": "https://auth.woolworths.com.au/",
        "X-Requested-With": "XMLHttpRequest",
    }
    if extra_headers:
        headers.update(extra_headers)

    params = {
        "token": SCRAPEDO_KEY,
        "url": url,
        "render": "true",
        "super": "true",
        "country": "au",
        "session": SESSION_ID,
        "wait": "8000",
        "method": "POST",
        "payload": urlencode(payload),
        "headers": json.dumps(headers),
    }
    return requests.get("https://api.scrape.do", params=params, timeout=120)


# ============================================================================
# ZenRows helpers
# ============================================================================
def zenrows_get(url: str, extra_params: dict = None) -> requests.Response:
    """GET a URL through ZenRows with JS rendering."""
    params = {
        "apikey": ZENROWS_KEY,
        "url": url,
        "js_render": "true",
        "premium_proxy": "true",
        "wait_for": "body",
        "wait": "8000",
        "session_id": SESSION_ID,
    }
    if extra_params:
        params.update(extra_params)
    return requests.get("https://api.zenrows.com/v1/", params=params, timeout=120)


def zenrows_post(url: str, payload: dict) -> requests.Response:
    """POST to a URL through ZenRows with JS rendering."""
    params = {
        "apikey": ZENROWS_KEY,
        "url": url,
        "js_render": "true",
        "premium_proxy": "true",
        "wait_for": "body",
        "wait": "8000",
        "session_id": SESSION_ID,
        "method": "POST",
        "data": urlencode(payload),
        "headers": json.dumps({
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/html",
            "Origin": "https://auth.woolworths.com.au",
            "X-Requested-With": "XMLHttpRequest",
        }),
    }
    return requests.get("https://api.zenrows.com/v1/", params=params, timeout=120)


# ============================================================================
# Auth0 login flow
# ============================================================================
def run_login_flow(service: str, get_fn, post_fn) -> Optional[str]:
    """Run the full Auth0 → Woolworths login flow through a scraping service.

    Returns cookie string on success, None on failure.
    """
    print(f"\n{'='*60}")
    print(f"SERVICE: {service}")
    print(f"{'='*60}")

    # Step 1: Load login page → get Auth0 page
    print("  [1/6] Loading /shop/securelogin...")
    try:
        r1 = get_fn("https://www.woolworths.com.au/shop/securelogin")
        print(f"  HTTP {r1.status_code}, {len(r1.text)} bytes")
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return None

    html1 = r1.text

    # Check if we're on Auth0 or still on Woolworths
    if "auth.woolworths.com.au" not in html1 and "auth0" not in html1.lower():
        # We might need to follow the redirect manually
        print("  -> Not on Auth0 page, trying /auth/login directly...")
        try:
            r1 = get_fn("https://www.woolworths.com.au/auth/login")
            print(f"  HTTP {r1.status_code}, {len(r1.text)} bytes")
            html1 = r1.text
        except Exception as exc:
            print(f"  ERROR: {exc}")
            return None

    # Step 2: Extract Auth0 state and CSRF
    print("  [2/6] Extracting Auth0 state...")
    state_match = re.search(r'state=([a-zA-Z0-9_\-]+)', html1)
    state = state_match.group(1) if state_match else None

    csrf_match = re.search(r'name="_csrf"[^>]*value="([^"]+)"', html1)
    csrf = csrf_match.group(1) if csrf_match else ""

    if not state:
        print("  FAIL: Could not extract state parameter")
        # Save HTML for debugging
        debug_path = OUTPUT_DIR / f"{service}_step1.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(html1[:50000])
        print(f"  Saved debug HTML: {debug_path}")
        return None

    print(f"  State: {state[:40]}...")

    # Step 3: POST email to Auth0
    print("  [3/6] POST email to Auth0 identifier...")
    identifier_url = "https://auth.woolworths.com.au/u/login/identifier"
    try:
        r3 = post_fn(identifier_url, {
            "identifier": WOOL_USER,
            "state": state,
            "action": "default",
        })
        print(f"  HTTP {r3.status_code}, {len(r3.text)} bytes")
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return None

    # Step 4: POST password to Auth0
    print("  [4/6] POST password to Auth0...")
    password_url = "https://auth.woolworths.com.au/u/login/password"
    try:
        r4 = post_fn(password_url, {
            "password": WOOL_PASS,
            "state": state,
            "action": "default",
        })
        print(f"  HTTP {r4.status_code}, {len(r4.text)} bytes")
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return None

    # Check for MFA
    if "mfa" in r4.text.lower() or "2fa" in r4.text.lower():
        print("  -> MFA challenge detected (needs manual code)")
        # Save the MFA page for analysis
        debug_path = OUTPUT_DIR / f"{service}_mfa.html"
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(r4.text[:50000])
        print(f"  MFA page saved: {debug_path}")
        return None

    # Step 5: Follow callback to Woolworths
    print("  [5/6] Following callback to Woolworths...")
    try:
        r5 = get_fn("https://www.woolworths.com.au/")
        print(f"  HTTP {r5.status_code}, {len(r5.text)} bytes")
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return None

    # Step 6: Test cookies against mylists API
    print("  [6/6] Testing cookies against mylists API...")

    # We need to extract the cookies from the scraping service
    # Scrape.do returns cookies in response headers or via session
    # Use a GET to /apis/ui/mylists through the same session
    try:
        r6 = get_fn("https://www.woolworths.com.au/apis/ui/mylists")
        print(f"  HTTP {r6.status_code}, {len(r6.text)} bytes")

        if r6.status_code == 200:
            try:
                data = r6.json()
                lists = data.get("Response", [])
                print(f"  SUCCESS! {len(lists)} lists found:")
                for lst in lists:
                    name = lst.get("Name", "?")
                    lid = lst.get("ListId", "?")
                    count = lst.get("ItemCount", "?")
                    print(f"    [{lid}] \"{name}\" ({count} items)")

                # We can't get raw cookies from Scrape.do/ZenRows session,
                # but we've confirmed they work. Save the response.
                return "session_works"  # Marker that session auth works
            except Exception:
                print(f"  Response (not JSON): {r6.text[:200]}")
        elif r6.status_code == 403:
            print("  -> 403: Auth failed or session lost")
        else:
            print(f"  -> Unexpected: {r6.text[:200]}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    return None


# ============================================================================
# Direct approach: try to get cookies from scraping service headers
# ============================================================================
def try_direct_cookie_extraction(service: str, get_fn) -> Optional[str]:
    """Try a simpler approach: load mylists page and extract cookies."""
    print(f"\n  Direct approach: load mylists page through {service}...")
    try:
        r = get_fn("https://www.woolworths.com.au/shop/mylists")
        print(f"  HTTP {r.status_code}, {len(r.text)} bytes")

        # Check if we got the mylists page (not login redirect)
        if "mylist" in r.text.lower() or "saved list" in r.text.lower():
            print("  -> Got mylists page content!")
        elif "login" in r.text.lower():
            print("  -> Redirected to login (no cookies)")
        else:
            print(f"  Page snippet: {r.text[:300]}")

        # Try to access API through same session
        r2 = get_fn("https://www.woolworths.com.au/apis/ui/mylists")
        print(f"  API test: HTTP {r2.status_code}")
        if r2.status_code == 200:
            try:
                data = r2.json()
                lists = data.get("Response", [])
                if lists:
                    print(f"  Lists: {len(lists)}")
                    for lst in lists:
                        print(f"    [{lst.get('ListId')}] \"{lst.get('Name')}\"")
                    return "session_works"
            except Exception:
                pass

    except Exception as exc:
        print(f"  ERROR: {exc}")

    return None


# ============================================================================
# Main
# ============================================================================
def main():
    print("PHASE 9.0.b — WOOLWORTHS LOGIN VIA SCRAPING SERVICES")
    print("=" * 60)
    print(f"Scrape.do key: {'SET' if SCRAPEDO_KEY else 'MISSING'}")
    print(f"ZenRows key:  {'SET' if ZENROWS_KEY else 'MISSING'}")
    print(f"Credentials:  {'SET' if WOOL_USER and WOOL_PASS else 'MISSING'}")
    print(f"Session:      {SESSION_ID}")

    if not WOOL_USER or not WOOL_PASS:
        print("\nFAIL: Credentials not set")
        return 1

    results = {}

    # ---- Attempt 1: Scrape.do ----
    if SCRAPEDO_KEY:
        result = run_login_flow("Scrape.do", scrapedo_get, scrapedo_post)
        results["scrapedo_full"] = result

        # If full flow failed, try direct cookie approach
        if not result:
            result2 = try_direct_cookie_extraction("Scrape.do", scrapedo_get)
            results["scrapedo_direct"] = result2
    else:
        print("\nScrape.do: SKIPPED (no API key)")

    # ---- Attempt 2: ZenRows ----
    if ZENROWS_KEY:
        result = run_login_flow("ZenRows", zenrows_get, zenrows_post)
        results["zenrows_full"] = result

        if not result:
            result2 = try_direct_cookie_extraction("ZenRows", zenrows_get)
            results["zenrows_direct"] = result2
    else:
        print("\nZenRows: SKIPPED (no API key)")

    # ---- Summary ----
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for key, val in results.items():
        status = "WORKS" if val else "FAILED"
        print(f"  {key}: {status}")

    any_success = any(results.values())
    if any_success:
        print("\nSUCCESS: At least one scraping service can authenticate")
        return 0
    else:
        print("\nFAIL: Neither scraping service could authenticate")
        print("Will need headed browser approach (see next step)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
