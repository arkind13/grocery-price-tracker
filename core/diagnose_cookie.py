"""Phase 9.0.b — Cookie & Login Diagnostic.

Diagnoses why WOOLWORTHS_COOKIE returns 403 and why Playwright login fails.
Prints diagnostic info WITHOUT exposing secret values.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Env loading
# ---------------------------------------------------------------------------
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


# ============================================================================
# STEP 1: Cookie structure analysis (NO secret values printed)
# ============================================================================
def diagnose_cookie():
    """Analyze WOOLWORTHS_COOKIE structure without printing values."""
    print("=" * 60)
    print("STEP 1: Cookie Structure Analysis")
    print("=" * 60)

    cookie = os.getenv("WOOLWORTHS_COOKIE", "")
    if not cookie:
        print("  [FAIL] WOOLWORTHS_COOKIE is empty")
        return

    print(f"  Raw length: {len(cookie)} chars")

    # Check if it looks like a cookie string
    cookie_parts = cookie.split(";")
    print(f"  Semicolon-separated parts: {len(cookie_parts)}")

    # Look for key cookie names
    key_names = ["JSESSIONID", "session", "SESSION", "Token", "token",
                 "Cookie", "cookie", "Authorization", "auth", "wow.",
                 "_abck", "ak_bmsc", "bm_sz"]
    found_keys = []
    for part in cookie_parts:
        part = part.strip()
        for key in key_names:
            if part.lower().startswith(key.lower() + "=") or key + "=" in part:
                found_keys.append(part[:80])
                break

    if found_keys:
        print(f"  Recognized cookie keys: {len(found_keys)}")
        for k in found_keys:
            print(f"    ...{k}...")
    else:
        print("  [WARN] No recognized cookie keys found")

    # Check if it might be JSON
    if cookie.strip().startswith("{"):
        print("  Format: JSON object")
        try:
            d = json.loads(cookie)
            print(f"  JSON keys: {list(d.keys())}")
        except json.JSONDecodeError:
            print("  [WARN] Looks like JSON but invalid")
    else:
        print("  Format: raw cookie string")


# ============================================================================
# STEP 2: Try Woolworths API with different header strategies
# ============================================================================
def diagnose_api_access():
    """Try Woolworths APIs with different header combos."""
    import requests

    print("\n" + "=" * 60)
    print("STEP 2: Woolworths API Access Tests")
    print("=" * 60)

    cookie = os.getenv("WOOLWORTHS_COOKIE", "")
    if not cookie:
        print("  [SKIP] No cookie available")
        return

    endpoints = [
        ("mylists", "https://www.woolworths.com.au/apis/ui/mylists"),
        ("lists", "https://www.woolworths.com.au/apis/ui/lists"),
        ("bootstrap", "https://www.woolworths.com.au/apis/ui/Bootstrap"),
        ("homepage", "https://www.woolworths.com.au/"),
    ]

    header_sets = [
        {
            "name": "minimal",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Cookie": cookie,
            },
        },
        {
            "name": "full_referer",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.woolworths.com.au/shop/mylists",
                "Origin": "https://www.woolworths.com.au",
                "Cookie": cookie,
            },
        },
        {
            "name": "with_accept_lang",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-AU,en;q=0.9",
                "Referer": "https://www.woolworths.com.au/shop/mylists",
                "Origin": "https://www.woolworths.com.au",
                "Cookie": cookie,
            },
        },
    ]

    for ep_name, ep_url in endpoints:
        for hs in header_sets:
            try:
                r = requests.get(ep_url, headers=hs["headers"], timeout=15,
                                 allow_redirects=True)
                status = r.status_code
                body_len = len(r.text)
                body_preview = r.text[:100].replace("\n", " ")

                # Check for redirect
                is_redirect = r.history and len(r.history) > 0

                print(f"  {ep_name:12s} | {hs['name']:18s} | HTTP {status} | "
                      f"{body_len}B | redirect={is_redirect} | {body_preview[:70]}")
            except requests.RequestException as exc:
                print(f"  {ep_name:12s} | {hs['name']:18s} | ERROR: {exc}")

            time.sleep(0.5)  # be polite


# ============================================================================
# STEP 3: Playwright login page structure capture
# ============================================================================
def diagnose_login_page():
    """Open Woolworths login page and capture page structure."""
    print("\n" + "=" * 60)
    print("STEP 3: Woolworths Login Page Structure")
    print("=" * 60)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [SKIP] Playwright not installed")
        return

    output_dir = _REPO_ROOT / "data" / "diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        try:
            print("  Navigating to Woolworths login page...")
            page.goto("https://www.woolworths.com.au/shop/login",
                      wait_until="networkidle", timeout=60000)
            print(f"  Final URL: {page.url}")
            print(f"  Page title: {page.title()}")

            # Screenshot
            ss_path = output_dir / "wool_login_page.png"
            page.screenshot(path=str(ss_path))
            print(f"  Screenshot saved: {ss_path}")

            # Find all input elements
            inputs = page.query_selector_all("input")
            print(f"\n  Input elements found: {len(inputs)}")
            for i, inp in enumerate(inputs):
                try:
                    inp_type = inp.get_attribute("type") or "text"
                    inp_id = inp.get_attribute("id") or ""
                    inp_name = inp.get_attribute("name") or ""
                    inp_placeholder = inp.get_attribute("placeholder") or ""
                    inp_aria = inp.get_attribute("aria-label") or ""
                    print(f"    [{i}] type={inp_type} id='{inp_id}' "
                          f"name='{inp_name}' placeholder='{inp_placeholder}' "
                          f"aria-label='{inp_aria}'")
                except Exception:
                    print(f"    [{i}] (error reading attributes)")

            # Find all buttons
            buttons = page.query_selector_all("button")
            print(f"\n  Button elements found: {len(buttons)}")
            for i, btn in enumerate(buttons):
                try:
                    btn_text = btn.inner_text()[:80].replace("\n", " ")
                    btn_type = btn.get_attribute("type") or ""
                    btn_id = btn.get_attribute("id") or ""
                    print(f"    [{i}] type={btn_type} id='{btn_id}' text='{btn_text}'")
                except Exception:
                    print(f"    [{i}] (error reading attributes)")

            # Check for iframes
            frames = page.frames
            print(f"\n  Frames: {len(frames)}")
            for f in frames:
                print(f"    name='{f.name}' url='{f.url[:100]}'")

            # Save page HTML snippet
            html_path = output_dir / "wool_login_page.html"
            html = page.content()
            # Only save relevant parts to avoid huge files
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html[:50000])
            print(f"  HTML snippet saved: {html_path}")

        except Exception as exc:
            print(f"  [ERROR] Page load/analysis failed: {exc}")
            # Try screenshot anyway
            try:
                ss_path = output_dir / "wool_login_error.png"
                page.screenshot(path=str(ss_path))
                print(f"  Error screenshot saved: {ss_path}")
            except Exception:
                pass
        finally:
            browser.close()


# ============================================================================
# STEP 4: Check Woolworths creds structure
# ============================================================================
def diagnose_credentials():
    """Check credential format without printing values."""
    print("\n" + "=" * 60)
    print("STEP 4: Credential Format Check")
    print("=" * 60)

    for var in ["WOOLWORTHS_USER", "WOOLWORTHS_PASS"]:
        val = os.getenv(var, "")
        if not val:
            print(f"  [FAIL] {var} is empty/missing")
        else:
            at_pos = val.find("@") if var == "WOOLWORTHS_USER" else -1
            print(f"  {var}: {len(val)} chars"
                  + (f", contains '@' at pos {at_pos}" if at_pos > 0 else ""))


# ============================================================================
# Main
# ============================================================================
def main():
    print("WOOLWORTHS COOKIE & LOGIN DIAGNOSTIC")
    print("=" * 60)
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    diagnose_cookie()
    diagnose_api_access()
    diagnose_credentials()
    diagnose_login_page()

    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)
    print(f"Screenshots/HTML in: grocery-price-tracker/data/diagnostics/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
