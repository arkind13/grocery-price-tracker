"""Phase 9.0.b — curl_cffi TLS fingerprint impersonation test.

Uses curl_cffi to impersonate Chrome 131 TLS fingerprint, bypassing
Akamai bot detection at the TLS layer. Also tries with the existing cookie.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_WORKSPACE = _REPO_ROOT.parent


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

from curl_cffi import requests


def test_with_cookie(cookie_str: str, label: str):
    """Test Woolworths API with curl_cffi impersonating Chrome."""
    print(f"\n--- {label} ---")
    print(f"  Cookie length: {len(cookie_str)}")

    # Impersonate Chrome 131
    try:
        r = requests.get(
            "https://www.woolworths.com.au/apis/ui/mylists",
            headers={
                "Accept": "application/json, text/plain, */*",
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
            print(f"  Lists found: {len(lists)}")
            for lst in lists:
                print(f"    [{lst.get('ListId')}] \"{lst.get('Name')}\" "
                      f"({lst.get('ItemCount', '?')} items)")
            return True, data
        else:
            print(f"  Body: {r.text[:200]}")
            return False, None
    except Exception as exc:
        print(f"  Error: {exc}")
        return False, None


def test_woolworths_homepage():
    """Test if we can even reach the homepage with impersonation."""
    print("\n--- Woolworths Homepage (Chrome 131 impersonation) ---")
    try:
        r = requests.get(
            "https://www.woolworths.com.au/",
            impersonate="chrome131",
            timeout=30,
        )
        print(f"  HTTP {r.status_code}")
        print(f"  Content length: {len(r.content)}")
        print(f"  Title: {r.text[:500]}")
        return r.status_code == 200
    except Exception as exc:
        print(f"  Error: {exc}")
        return False


def main():
    print("curl_cffi TLS FINGERPRINT IMPERSONATION TEST")
    print("=" * 60)

    # Test 1: Can we reach the homepage?
    ok = test_woolworths_homepage()

    # Test 2: Try with existing cookie
    cookie = os.getenv("WOOLWORTHS_COOKIE", "")
    if cookie:
        success, data = test_with_cookie(cookie, "Existing WOOLWORTHS_COOKIE")
        if success:
            print("\n[SUCCESS] Existing cookie works with TLS impersonation!")
            return 0

    # Test 3: Try without cookie (just to see if TLS impersonation alone helps)
    success, data = test_with_cookie("", "No cookie (just TLS impersonation)")
    if success:
        print("\nHomepage accessible but API needs auth")

    print("\n[RESULT] curl_cffi TLS impersonation did not bypass Akamai with current cookie")
    return 1


if __name__ == "__main__":
    sys.exit(main())
