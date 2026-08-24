"""Phase 9.0.b — Chrome Profile Cookie Extraction.

Reads cookies directly from the user's Chrome browser profile where
they have already logged into Woolworths manually. This bypasses Akamai
bot detection entirely since the cookies were obtained via a real browser.

Never prints cookie values.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


def find_chrome_cookie_db() -> Path | None:
    """Find Chrome's Cookie database in default profile locations."""
    candidates = [
        Path.home() / "AppData" / "Local" / "Google" / "Chrome"
        / "User Data" / "Default" / "Network" / "Cookies",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome"
        / "User Data" / "Default" / "Cookies",
        Path.home() / "AppData" / "Local" / "Chromium"
        / "User Data" / "Default" / "Network" / "Cookies",
        Path.home() / "AppData" / "Local" / "Microsoft" / "Edge"
        / "User Data" / "Default" / "Network" / "Cookies",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def extract_woolworths_cookies(db_path: Path) -> str | None:
    """Extract Woolworths cookies from Chrome's SQLite cookie DB.

    Chrome encrypts cookies on disk, so this only works if Chrome is not
    running or if we can decrypt them. We'll try the raw approach first.
    """
    try:
        # Try using browser_cookie3 if available
        import browser_cookie3

        print("  Using browser_cookie3 to extract cookies...")
        cj = browser_cookie3.chrome(domain_name="woolworths.com.au")
        cookies = list(cj)
        if cookies:
            cookie_str = "; ".join(
                f"{c.name}={c.value}" for c in cookies
            )
            print(f"  Extracted {len(cookies)} cookies for woolworths.com.au")
            print(f"  Cookie string length: {len(cookie_str)}")
            return cookie_str
        else:
            print("  No Woolworths cookies found via browser_cookie3")
            return None

    except ImportError:
        print("  browser_cookie3 not installed, trying raw SQLite...")
        return _extract_raw(db_path)
    except Exception as exc:
        print(f"  browser_cookie3 failed: {exc}")
        print("  Falling back to raw SQLite...")
        return _extract_raw(db_path)


def _extract_raw(db_path: Path) -> str | None:
    """Raw SQLite cookie extraction (won't work for encrypted cookies)."""
    try:
        # Copy DB to avoid lock conflicts
        import shutil
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        shutil.copy2(db_path, tmp.name)
        tmp.close()

        conn = sqlite3.connect(tmp.name)
        cursor = conn.cursor()

        # Query cookies for woolworths.com.au
        cursor.execute(
            "SELECT host_key, name, encrypted_value FROM cookies "
            "WHERE host_key LIKE '%woolworths.com.au%'"
        )
        rows = cursor.fetchall()
        conn.close()

        # Clean up temp file
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

        if not rows:
            print("  No Woolworths cookies found in Chrome DB")
            return None

        print(f"  Found {len(rows)} Woolworths cookie entries in Chrome DB")
        print("  Note: Chrome encrypts cookies — cannot decrypt without keychain access")
        print("  Cookie names found:")
        for host, name, _ in rows:
            print(f"    {host}: {name}")

        return None

    except Exception as exc:
        print(f"  Raw extraction failed: {exc}")
        return None


def test_cookie(cookie_str: str) -> bool:
    """Test if a cookie string works against Woolworths API."""
    import requests

    print("\n  Testing cookie against Woolworths API...")
    try:
        r = requests.get(
            "https://www.woolworths.com.au/apis/ui/mylists",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.woolworths.com.au/shop/mylists",
                "Origin": "https://www.woolworths.com.au",
                "Cookie": cookie_str,
            },
            timeout=30,
        )
        print(f"  HTTP status: {r.status_code}")
        if r.status_code == 200:
            print("  [SUCCESS] Cookie works!")
            data = r.json()
            lists = data.get("Response", [])
            print(f"  Lists found: {len(lists)}")
            for lst in lists:
                print(f"    [{lst.get('ListId')}] \"{lst.get('Name')}\" "
                      f"({lst.get('ItemCount', '?')} items)")
            return True
        else:
            print(f"  Response: {r.text[:200]}")
            return False
    except Exception as exc:
        print(f"  Test failed: {exc}")
        return False


def try_install_browser_cookie3():
    """Try to install browser_cookie3."""
    import subprocess
    print("  Attempting to install browser_cookie3...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "browser-cookie3"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("  Installed successfully")
        return True
    except Exception:
        print("  Install failed — manual install may be needed")
        return False


def main():
    print("CHROME COOKIE EXTRACTION FOR WOOLWORTHS")
    print("=" * 60)

    db_path = find_chrome_cookie_db()
    if not db_path:
        print("ERROR: Could not find Chrome/Edge Cookie database")
        print("\nTry installing browser_cookie3:")
        print("  pip install browser-cookie3")
        print("Then re-run this script.")
        return 1

    print(f"Found cookie DB: {db_path}")

    # Try extraction
    cookie = extract_woolworths_cookies(db_path)

    if cookie:
        # Test it
        ok = test_cookie(cookie)
        if ok:
            print("\n[SUCCESS] Fresh cookie obtained from Chrome profile!")
            print(f"Cookie length: {len(cookie)} chars")
            # Save for use
            output_path = Path(__file__).resolve().parent.parent / "data" / "diagnostics" / "chrome_cookie.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(cookie)
            print(f"Saved to: {output_path}")
            print("\nTo update .env, copy the cookie string and replace WOOLWORTHS_COOKIE.")
            return 0
        else:
            print("\nCookie extracted but does not work (may be expired)")
            return 1
    else:
        print("\nCould not extract Woolworths cookies from Chrome.")
        print("Options:")
        print("  1. Install browser_cookie3: pip install browser-cookie3")
        print("  2. Or: log in to Woolworths in Chrome, then re-run")
        return 1


if __name__ == "__main__":
    sys.exit(main())
