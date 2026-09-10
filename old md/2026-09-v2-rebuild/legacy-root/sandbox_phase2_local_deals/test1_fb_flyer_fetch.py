#!/usr/bin/env python3
"""Test 1 sandbox harness — fetch the latest promo flyer image URL from a
Facebook page (Phase 2: Localised Store Specials).

Sandbox ONLY: this file is test evidence for pre-arch.md, not production
code. It compares the two candidate approaches with NO new subscriptions:

    --mode mbasic     Free probe: plain HTTPS request to
                      mbasic.facebook.com/<page-id> (no login, no credits).
                      Historically served public page content logged-out.
    --mode scrapedo   One Scrape.do render call against the public page
                      (uses the existing SCRAPEDO_API_KEY; 1-2 credits max).
    --mode local      Headed local browser (Playwright Chromium, persistent
                      profile) - the Phase-1-proven path for robot walls.
                      FB is an IDENTITY wall though, so the first run is
                      expected to hit a login screen; the user logs in once
                      in the visible window and the profile persists it
                      (same pattern as session_refresh.py).

Output: findings JSON in this folder (fb_fetch_findings.json) recording
per-mode outcome + the flyer image URLs found (scontent CDN links).
The API key is read from the workspace-root .env at runtime and is NEVER
printed, logged, or written to the findings file.

Usage:
    uv run test1_fb_flyer_fetch.py --mode mbasic --page-id 100071472636159
    uv run --with requests test1_fb_flyer_fetch.py --mode scrapedo --page-id 100071472636159
    uv run --with playwright test1_fb_flyer_fetch.py --mode local --page-id 100071472636159
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FINDINGS_PATH = HERE / "fb_fetch_findings.json"
LOCAL_PROFILE_DIR = HERE / "fb_local_profile"  # sandbox-local persistent profile

TARGET_PAGES = {
    "dunya": "100071472636159",
    "merjan": "61578274311504",
    "fruitopia": "100092972080784",
    "abusalim": "61592534263358",
}

# Facebook image CDN hostnames (image srcs we care about).
SCONTENT_RE = re.compile(
    r"https://scontent[^\"'\s\\]+?\.(?:jpg|png|webp)[^\"'\s\\]*"
)

# Login-wall fingerprints: any of these in the HTML means we were NOT
# shown real page content.
LOGIN_WALL_MARKERS = (
    "login_form",
    "you must log in to continue",
    "/login/?next=",
    "loginPageID",
)


def _load_root_env() -> None:
    """Walk up from this file to the workspace root and load .env into
    os.environ (first .env found wins; values are never printed)."""
    for parent in [HERE, *HERE.parents]:
        env_path = parent / ".env"
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
            except OSError as exc:
                print(f"[warn] could not read .env: {exc.__class__.__name__}")
            return


def _has_login_wall(html: str) -> bool:
    """True when the HTML looks like a Facebook login wall."""
    low = html.lower()
    return any(marker in low for marker in LOGIN_WALL_MARKERS)


def _extract_image_urls(html: str) -> list[str]:
    """Deduplicated scontent image URLs in first-seen order."""
    seen: dict[str, None] = {}
    for url in SCONTENT_RE.findall(html):
        seen.setdefault(url, None)
    return list(seen)


def probe_mbasic(page_id: str, timeout_s: float = 20.0) -> dict:
    """Free, credit-free probe of mbasic.facebook.com (plain requests)."""
    import urllib.request

    url = f"https://mbasic.facebook.com/{page_id}"
    result: dict = {"mode": "mbasic", "url": url, "ok": False}
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0 Safari/537.36"),
            "Accept-Language": "en-AU,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        result["http_status"] = resp.status
    except Exception as exc:  # noqa: BLE001 — sandbox: record and continue
        result["error"] = f"{exc.__class__.__name__}: {exc}"
        return result

    result["login_wall"] = _has_login_wall(html)
    result["image_urls"] = _extract_image_urls(html)
    result["image_count"] = len(result["image_urls"])
    result["ok"] = (not result["login_wall"]) and result["image_count"] > 0
    return result


def probe_scrapedo(page_id: str, timeout_s: float = 90.0,
                   path: str = "") -> dict:
    """One Scrape.do rendered fetch of the public page (1 credit-ish)."""
    import requests

    token = os.getenv("SCRAPEDO_API_KEY", "")
    desktop_url = f"https://www.facebook.com/{page_id}{path}"
    result: dict = {"mode": "scrapedo", "url": desktop_url, "ok": False}
    if not token:
        result["error"] = "SCRAPEDO_API_KEY not set in .env"
        return result

    params = {
        "token": token,
        "url": desktop_url,
        "render": "true",          # FB needs JS
        "geoCode": "au",           # AU exit node (Phase-1 recipe)
        "country": "au",
    }
    try:
        resp = requests.get("https://api.scrape.do", params=params,
                            timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{exc.__class__.__name__}: {exc}"
        return result

    result["http_status"] = resp.status_code
    html = resp.text or ""
    result["login_wall"] = _has_login_wall(html)
    result["image_urls"] = _extract_image_urls(html)
    result["image_count"] = len(result["image_urls"])
    result["ok"] = resp.status_code == 200 and result["image_count"] > 0
    return result


def probe_local(page_id: str, headless: bool = False,
                scrolls: int = 3, timeout_s: float = 60.0) -> dict:
    """Headed local Chromium with a persistent profile (Phase-1 pattern).

    First run: FB will show a login wall INSIDE the window — that is the
    expected finding; the profile persists a one-time manual login.
    """
    from playwright.sync_api import sync_playwright

    desktop_url = f"https://www.facebook.com/{page_id}"
    result: dict = {"mode": "local", "url": desktop_url,
                    "headless": headless, "ok": False}
    LOCAL_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(LOCAL_PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            locale="en-AU",
        )
        page = browser.new_page()
        try:
            page.goto(desktop_url, timeout=timeout_s * 1000,
                      wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            for _ in range(scrolls):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(1500)
            html = page.content()
            result["final_url"] = page.url
        finally:
            browser.close()

    result["login_wall"] = _has_login_wall(html)
    result["image_urls"] = _extract_image_urls(html)
    result["image_count"] = len(result["image_urls"])
    result["ok"] = (not result["login_wall"]) and result["image_count"] > 0
    return result


def probe_zenrows(page_id: str, timeout_s: float = 90.0,
                  url_override: str | None = None) -> dict:
    """ZenRows rendered fetch of the public page (fallback provider).

    Mirrors scraping_api/scrape.py: ZENROWS_API_KEY, js_render=true,
    endpoint https://api.zenrows.com/v1/.
    """
    import requests

    token = os.getenv("ZENROWS_API_KEY", "")
    desktop_url = url_override or f"https://www.facebook.com/{page_id}"
    result: dict = {"mode": "zenrows", "url": desktop_url, "ok": False}
    if not token:
        result["error"] = "ZENROWS_API_KEY not set in .env"
        return result

    params = {
        "apikey": token,
        "url": desktop_url,
        "js_render": "true",
    }
    try:
        resp = requests.get("https://api.zenrows.com/v1/", params=params,
                            timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{exc.__class__.__name__}: {exc}"
        return result

    result["http_status"] = resp.status_code
    html = resp.text or ""
    if resp.status_code != 200:
        # Capture the provider's error body (key masked) so the 400
        # becomes diagnosable instead of opaque.
        result["error_body"] = html[:400].replace(token, "***MASKED***")
    result["login_wall"] = _has_login_wall(html)
    result["image_urls"] = _extract_image_urls(html)
    result["image_count"] = len(result["image_urls"])
    result["ok"] = resp.status_code == 200 and result["image_count"] > 0
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", required=True,
                        choices=["mbasic", "scrapedo", "zenrows", "local"])
    parser.add_argument("--page-id", default=TARGET_PAGES["dunya"],
                        help="FB page id (default: Dunya Butchery)")
    parser.add_argument("--headless", action="store_true",
                        help="local mode: run headless (diagnostic only)")
    parser.add_argument("--scrolls", type=int, default=3,
                        help="local mode: page scrolls before capture")
    parser.add_argument("--url-override", default=None,
                        help="zenrows mode: probe an alternative URL form "
                             "(e.g. https://m.facebook.com/<id>)")
    parser.add_argument("--path", default="",
                        help="scrapedo mode: page path after the page id "
                             "(e.g. '/photos' for the photos tab)")
    args = parser.parse_args()

    if args.page_id in TARGET_PAGES:
        # allow passing a store alias instead of the raw id
        args.page_id = TARGET_PAGES[args.page_id]

    _load_root_env()

    runners = {
        "mbasic": lambda: probe_mbasic(args.page_id),
        "scrapedo": lambda: probe_scrapedo(args.page_id, path=args.path),
        "zenrows": lambda: probe_zenrows(args.page_id,
                                         url_override=args.url_override),
        "local": lambda: probe_local(args.page_id,
                                     headless=args.headless,
                                     scrolls=args.scrolls),
    }
    finding = runners[args.mode]()

    # Merge into the findings file (never contains secrets).
    findings = {"runs": []}
    if FINDINGS_PATH.exists():
        try:
            findings = json.loads(FINDINGS_PATH.read_text("utf-8"))
        except (OSError, ValueError):
            findings = {"runs": []}
    findings["runs"].append(finding)
    FINDINGS_PATH.write_text(
        json.dumps(findings, indent=2, ensure_ascii=False), "utf-8")

    # Console summary (URLs truncated to keep the log readable).
    print(json.dumps(
        {**finding, "image_urls": finding.get("image_urls", [])[:5]},
        indent=2, ensure_ascii=False))
    return 0 if finding.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
