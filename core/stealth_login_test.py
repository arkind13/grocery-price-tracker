"""Phase 9.0.b — Stealth Login Test (correct API).

Uses playwright_stealth.Stealth.apply_stealth_sync() to bypass Akamai.
"""
from __future__ import annotations

import json
import os
import sys
import time
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


def test_stealth_sync():
    """Use Stealth.apply_stealth_sync to bypass Akamai."""
    print("=" * 60)
    print("TEST: Stealth Sync -> Woolworths Login Page")
    print("=" * 60)

    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    stealth = Stealth(
        navigator_webdriver=True,
        navigator_user_agent=True,
        navigator_languages=True,
        navigator_platform=True,
        navigator_vendor=True,
        navigator_plugins=True,
        webgl_vendor=True,
        chrome_app=True,
        chrome_csi=True,
        chrome_load_times=True,
        hairline=True,
        iframe_content_window=True,
        media_codecs=True,
        navigator_hardware_concurrency=True,
        navigator_permissions=True,
        error_prototype=True,
        sec_ch_ua=True,
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-AU",
            timezone_id="Australia/Sydney",
        )
        stealth.apply_stealth_sync(context)

        page = context.new_page()

        try:
            print("  Navigating to login page...")
            resp = page.goto(
                "https://www.woolworths.com.au/shop/login",
                wait_until="networkidle",
                timeout=60000,
            )
            print(f"  HTTP status: {resp.status if resp else 'N/A'}")
            print(f"  Final URL: {page.url}")
            print(f"  Page title: {page.title()}")

            if "Access Denied" in page.title():
                print("  [FAIL] Still blocked by Akamai")
                ss_path = OUTPUT_DIR / "stealth_blocked.png"
                page.screenshot(path=str(ss_path))
                return False

            print("  [PASS] Login page loaded!")

            # Save screenshot
            ss_path = OUTPUT_DIR / "wool_stealth_login.png"
            page.screenshot(path=str(ss_path))
            print(f"  Screenshot: {ss_path}")

            # Find inputs
            page.wait_for_timeout(2000)
            inputs = page.query_selector_all("input")
            print(f"  Input elements: {len(inputs)}")
            for inp in inputs:
                try:
                    t = inp.get_attribute("type") or "?"
                    i = inp.get_attribute("id") or ""
                    n = inp.get_attribute("name") or ""
                    p = inp.get_attribute("placeholder") or ""
                    print(f"    type={t} id='{i}' name='{n}' placeholder='{p}'")
                except Exception:
                    pass

            # Find buttons
            buttons = page.query_selector_all("button")
            print(f"  Buttons: {len(buttons)}")
            for btn in buttons:
                try:
                    txt = btn.inner_text()[:60].replace("\n", " ")
                    t = btn.get_attribute("type") or ""
                    i = btn.get_attribute("id") or ""
                    print(f"    type={t} id='{i}' text='{txt}'")
                except Exception:
                    pass

            # Save HTML
            html_path = OUTPUT_DIR / "wool_stealth_login.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content()[:80000])
            print(f"  HTML: {html_path}")

            return True

        except Exception as exc:
            print(f"  [ERROR] {exc}")
            try:
                ss_path = OUTPUT_DIR / "stealth_error.png"
                page.screenshot(path=str(ss_path))
                print(f"  Error screenshot: {ss_path}")
            except Exception:
                pass
            return False
        finally:
            browser.close()


def test_stealth_with_login():
    """Use stealth to bypass Akamai, then log in and extract cookie."""
    print("\n" + "=" * 60)
    print("TEST: Stealth Login + Cookie Extraction")
    print("=" * 60)

    username = os.getenv("WOOLWORTHS_USER", "")
    password = os.getenv("WOOLWORTHS_PASS", "")

    if not username or not password:
        print("  [SKIP] No credentials")
        return False

    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    stealth = Stealth(
        navigator_webdriver=True,
        navigator_user_agent=True,
        navigator_languages=True,
        navigator_platform=True,
        navigator_vendor=True,
        navigator_plugins=True,
        webgl_vendor=True,
        chrome_app=True,
        chrome_csi=True,
        chrome_load_times=True,
        hairline=True,
        iframe_content_window=True,
        media_codecs=True,
        navigator_hardware_concurrency=True,
        navigator_permissions=True,
        error_prototype=True,
        sec_ch_ua=True,
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-AU",
            timezone_id="Australia/Sydney",
        )
        stealth.apply_stealth_sync(context)
        page = context.new_page()

        try:
            # Step 1: Reach login page
            print("  [1/6] Navigating to login...")
            page.goto("https://www.woolworths.com.au/shop/login",
                      wait_until="networkidle", timeout=60000)
            print(f"  Title: {page.title()}")

            if "Access Denied" in page.title():
                print("  [FAIL] Blocked")
                return False

            page.wait_for_timeout(3000)

            # Step 2: Find email field
            print("  [2/6] Finding email field...")
            email_sel = page.query_selector("#loginEmail")
            if not email_sel:
                # Try other selectors
                for sel in ['input[type="email"]', 'input[name="email"]',
                            '#email', '#login-email']:
                    email_sel = page.query_selector(sel)
                    if email_sel:
                        print(f"    Found: {sel}")
                        break
            if not email_sel:
                print("    Email field not found, checking page content...")
                print(f"    Page text snippet: {page.inner_text('body')[:300]}")
                return False
            print("    Found email field")

            # Step 3: Enter email
            print("  [3/6] Entering email...")
            email_sel.fill(username)

            # Step 4: Find and fill password
            print("  [4/6] Finding password field...")
            pw_sel = page.query_selector("#loginPassword")
            if not pw_sel:
                for sel in ['input[type="password"]', '#password']:
                    pw_sel = page.query_selector(sel)
                    if pw_sel:
                        break
            if not pw_sel:
                print("    Password field not found")
                return False
            pw_sel.fill(password)

            # Step 5: Submit
            print("  [5/6] Submitting login...")
            submit = page.query_selector('button[type="submit"]')
            if not submit:
                for sel in ['button:has-text("Login")',
                            'button:has-text("Sign in")',
                            'button:has-text("Log in")']:
                    submit = page.query_selector(sel)
                    if submit:
                        break
            if submit:
                submit.click()
            else:
                pw_sel.press("Enter")
            print("    Submitted")

            # Wait for redirect / 2FA
            page.wait_for_timeout(5000)
            print(f"    Post-submit URL: {page.url}")
            print(f"    Post-submit title: {page.title()}")

            # Step 6: Extract cookies
            print("  [6/6] Extracting cookies...")
            cookies = context.cookies()
            print(f"    Got {len(cookies)} cookies")
            cookie_str = "; ".join(
                f"{c['name']}={c['value']}" for c in cookies
            )
            print(f"    Cookie length: {len(cookie_str)}")

            # Save cookie
            cookie_path = OUTPUT_DIR / "wool_fresh_cookie.txt"
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write(cookie_str)
            print(f"    Saved: {cookie_path}")

            # Test API with fresh cookie
            print("\n  Testing fresh cookie...")
            import requests
            r = requests.get(
                "https://www.woolworths.com.au/apis/ui/mylists",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.woolworths.com.au/shop/mylists",
                    "Origin": "https://www.woolworths.com.au",
                    "Cookie": cookie_str,
                },
                timeout=30,
            )
            print(f"    API status: {r.status_code}")
            if r.status_code == 200:
                print("    [SUCCESS] Cookie works!")
                data = r.json()
                lists = data.get("Response", [])
                print(f"    Lists: {len(lists)}")
                for lst in lists:
                    print(f"      [{lst.get('ListId')}] \"{lst.get('Name')}\"")
                return True
            else:
                print(f"    Failed: {r.text[:200]}")
                return False

        except Exception as exc:
            print(f"  [ERROR] {exc}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            browser.close()


def main():
    print("WOOLWORTHS STEALTH LOGIN")
    print("=" * 60)

    # Test 1: Can we reach login page?
    ok = test_stealth_sync()

    if ok:
        # Test 2: Login and get cookie
        ok2 = test_stealth_with_login()
        if ok2:
            print("\n[SUCCESS] Fresh cookie obtained and verified!")
            return 0
        else:
            print("\n[PARTIAL] Reached login page but login failed")
            return 1
    else:
        print("\n[FAIL] Could not reach login page")
        return 1


if __name__ == "__main__":
    sys.exit(main())
