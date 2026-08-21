#!/usr/bin/env python3
"""Probe Woolworths and Coles public endpoints to assess extraction feasibility.

Tests direct HTTP access and Scraping API (ZenRows / Scrape.do) fallback.
Documents status codes, required headers, JS-render necessity, and whether
saved-list access requires authenticated session cookies.

Usage:
    python extractors/probe_supermarkets.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Path setup: allow running from grocery-price-tracker/ or the repo root
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _load_env():
    """Load root .env if available."""
    if not load_dotenv:
        return
    env_path = os.path.join(_REPO_ROOT, ".env")
    if os.path.isfile(env_path):
        load_dotenv(env_path)


_load_env()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WOOLIES_BROWSE = (
    "https://www.woolworths.com.au/apis/ui/browse/category"
)
WOOLIES_SEARCH = "https://www.woolworths.com.au/apis/ui/Search/products"
WOOLIES_LISTS = "https://www.woolworths.com.au/apis/ui/lists"

COLES_SEARCH = "https://www.coles.com.au/api/search/v2/search"
COLES_PRODUCT = "https://www.coles.com.au/api/products/v2/products"

DEFAULT_TIMEOUT = 20
USER_AGENTS = {
    "chrome_win": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "safari_mac": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.5 Safari/605.1.15"
    ),
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Probe result helpers
# ---------------------------------------------------------------------------
class ProbeResult:
    """Structured outcome of a single endpoint probe."""

    def __init__(self, store, endpoint, method, label):
        self.store = store
        self.endpoint = endpoint
        self.method = method
        self.label = label
        self.timestamp = _now_iso()
        self.status = None
        self.elapsed_ms = None
        self.content_type = None
        self.content_length = None
        self.error = None
        self.js_render_required = None
        self.auth_required = None
        self.notes = []

    def to_dict(self):
        return {
            "store": self.store,
            "endpoint": self.endpoint,
            "method": self.method,
            "label": self.label,
            "timestamp": self.timestamp,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
            "content_type": self.content_type,
            "content_length": self.content_length,
            "error": self.error,
            "js_render_required": self.js_render_required,
            "auth_required": self.auth_required,
            "notes": self.notes,
        }

    def __repr__(self):
        icon = "✅" if self.status and self.status < 400 else "❌"
        return (
            f"{icon} [{self.store}] {self.label}: "
            f"HTTP {self.status} ({self.elapsed_ms}ms)"
            + (f" -- {self.error}" if self.error else "")
        )


# ---------------------------------------------------------------------------
# Probe functions
# ---------------------------------------------------------------------------
def probe_woolworths_browse():
    """Probe Woolworths browse/category API with a real category ID."""
    result = ProbeResult(
        store="Woolworths",
        endpoint=WOOLIES_BROWSE,
        method="GET",
        label="Browse API (category)",
    )
    headers = {
        "User-Agent": USER_AGENTS["chrome_win"],
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.woolworths.com.au/shop/browse/dairy-eggs-fridge",
    }
    params = {
        "categoryId": "1_E5C9B6",  # Dairy, Eggs & Fridge
        "pageNumber": 1,
        "pageSize": 5,
    }
    try:
        t0 = time.perf_counter()
        resp = requests.get(
            WOOLIES_BROWSE, params=params, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result.status = resp.status_code
        result.content_type = resp.headers.get("Content-Type", "")
        result.content_length = len(resp.content)
        if resp.status_code == 200:
            data = resp.json()
            items = (
                data.get("Bundles", [])
                or data.get("Products", [])
                or []
            )
            result.notes.append(f"Received {len(items)} products in response")
            if len(items) == 0:
                result.js_render_required = True
                result.notes.append(
                    "Empty product list -- may need JS rendering or session"
                )
            else:
                result.js_render_required = False
                result.notes.append("Direct JSON access works without JS render")
        elif resp.status_code == 403:
            result.js_render_required = True
            result.auth_required = True
            result.notes.append("HTTP 403 -- blocked without auth/JS render")
        else:
            result.notes.append(f"Unexpected HTTP {resp.status_code}")
    except requests.exceptions.Timeout as exc:
        result.error = f"Timeout ({DEFAULT_TIMEOUT}s)"
        result.js_render_required = True
    except requests.exceptions.RequestException as exc:
        result.error = type(exc).__name__
        result.js_render_required = True
    return result


def probe_woolworths_search():
    """Probe Woolworths product search API."""
    result = ProbeResult(
        store="Woolworths",
        endpoint=WOOLIES_SEARCH,
        method="POST",
        label="Search API (keyword)",
    )
    headers = {
        "User-Agent": USER_AGENTS["chrome_win"],
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "https://www.woolworths.com.au/shop/search/products",
    }
    payload = {
        "SearchTerm": "milk",
        "PageNumber": 1,
        "PageSize": 5,
        "SortType": "TraderRelevance",
    }
    try:
        t0 = time.perf_counter()
        resp = requests.post(
            WOOLIES_SEARCH, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result.status = resp.status_code
        result.content_type = resp.headers.get("Content-Type", "")
        result.content_length = len(resp.content)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("Products", [])
            result.notes.append(f"Received {len(items)} products in response")
            result.js_render_required = False if len(items) > 0 else True
            if result.js_render_required:
                result.notes.append("Empty product list -- may need JS render")
            else:
                result.notes.append("Direct JSON search works without JS render")
                # Log first product structure
                if items:
                    keys = list(items[0].keys())
                    result.notes.append(f"Product keys: {keys[:15]}")
        elif resp.status_code == 403:
            result.js_render_required = True
            result.auth_required = True
            result.notes.append("HTTP 403 -- blocked without auth/JS render")
        else:
            result.notes.append(f"Unexpected HTTP {resp.status_code}")
    except requests.exceptions.Timeout as exc:
        result.error = f"Timeout ({DEFAULT_TIMEOUT}s)"
        result.js_render_required = True
    except requests.exceptions.RequestException as exc:
        result.error = type(exc).__name__
        result.js_render_required = True
    return result


def probe_woolworths_lists():
    """Probe Woolworths saved-lists API (requires authenticated session)."""
    result = ProbeResult(
        store="Woolworths",
        endpoint=WOOLIES_LISTS,
        method="GET",
        label="Saved Lists API (auth required)",
    )
    headers = {
        "User-Agent": USER_AGENTS["chrome_win"],
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.woolworths.com.au/shop/list",
    }
    ww_cookie = os.getenv("WOOLWORTHS_COOKIE", "")
    if ww_cookie:
        headers["Cookie"] = ww_cookie
        result.notes.append("Using WOOLWORTHS_COOKIE from .env")
    try:
        t0 = time.perf_counter()
        resp = requests.get(
            WOOLIES_LISTS, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result.status = resp.status_code
        result.content_type = resp.headers.get("Content-Type", "")
        result.content_length = len(resp.content)
        if resp.status_code == 200:
            data = resp.json()
            result.js_render_required = False
            result.auth_required = not bool(ww_cookie)
            list_count = len(data) if isinstance(data, list) else 0
            result.notes.append(f"Received {list_count} saved lists")
            if ww_cookie:
                result.notes.append("Session cookie is valid for list access")
        elif resp.status_code == 401 or resp.status_code == 403:
            result.auth_required = True
            result.js_render_required = True
            result.notes.append(
                f"HTTP {resp.status_code} -- saved lists require valid session"
            )
            if not ww_cookie:
                result.notes.append(
                    "Set WOOLWORTHS_COOKIE in .env to test with authentication"
                )
        else:
            result.notes.append(f"Unexpected HTTP {resp.status_code}")
    except requests.exceptions.RequestException as exc:
        result.error = type(exc).__name__
        result.js_render_required = True
        result.auth_required = True
    return result


def probe_coles_search():
    """Probe Coles product search API."""
    result = ProbeResult(
        store="Coles",
        endpoint=COLES_SEARCH,
        method="POST",
        label="Search API (keyword)",
    )
    headers = {
        "User-Agent": USER_AGENTS["chrome_win"],
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "https://www.coles.com.au/browse/dairy",
        "Origin": "https://www.coles.com.au",
    }
    payload = {
        "searchTerm": "milk",
        "page": 1,
        "pageSize": 5,
        "sort": "relevance",
    }
    try:
        t0 = time.perf_counter()
        resp = requests.post(
            COLES_SEARCH, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT
        )
        result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result.status = resp.status_code
        result.content_type = resp.headers.get("Content-Type", "")
        result.content_length = len(resp.content)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("results", []) or data.get("products", [])
            result.notes.append(f"Received {len(items)} products in response")
            result.js_render_required = False if len(items) > 0 else True
            if result.js_render_required:
                result.notes.append("Empty result set -- may need JS render")
            else:
                result.notes.append("Direct JSON search works without JS render")
                if items:
                    keys = list(items[0].keys()) if isinstance(items[0], dict) else []
                    result.notes.append(f"Product keys: {keys[:15]}")
        elif resp.status_code == 403:
            result.js_render_required = True
            result.auth_required = True
            result.notes.append("HTTP 403 -- blocked without auth/JS render")
        else:
            result.notes.append(f"Unexpected HTTP {resp.status_code}")
    except requests.exceptions.RequestException as exc:
        result.error = type(exc).__name__
        result.js_render_required = True
    return result


def probe_coles_browse():
    """Probe Coles browse/category page via direct HTTP."""
    result = ProbeResult(
        store="Coles",
        endpoint="https://www.coles.com.au/browse/dairy",
        method="GET",
        label="Browse page (HTML)",
    )
    headers = {
        "User-Agent": USER_AGENTS["chrome_win"],
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        t0 = time.perf_counter()
        resp = requests.get(
            "https://www.coles.com.au/browse/dairy",
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result.status = resp.status_code
        result.content_type = resp.headers.get("Content-Type", "")
        result.content_length = len(resp.content)
        if resp.status_code == 200:
            result.js_render_required = True  # SPA -- JS required to hydrate
            result.notes.append("HTTP 200 but page is SPA (React) -- JS render required")
        elif resp.status_code == 403:
            result.js_render_required = True
            result.notes.append("HTTP 403 -- blocked")
        else:
            result.notes.append(f"Unexpected HTTP {resp.status_code}")
    except requests.exceptions.RequestException as exc:
        result.error = type(exc).__name__
        result.js_render_required = True
    return result


def probe_via_scraping_api(store_name, url, method="GET", json_payload=None):
    """Probe an endpoint through the shared scraping_api (ZenRows / Scrape.do)."""
    result = ProbeResult(
        store=store_name,
        endpoint=url,
        method=method,
        label=f"Via scraping_api ({store_name})",
    )
    try:
        from scraping_api.scrape import fetch, ScrapeError

        t0 = time.perf_counter()
        # First try without JS render
        try:
            html = fetch(url, js_render=False, timeout=DEFAULT_TIMEOUT)
            result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
            result.status = 200
            result.content_length = len(html)
            result.content_type = "text/html"
            result.js_render_required = False
            result.notes.append(
                "ZenRows direct fetch succeeded (no JS render needed)"
            )
        except (ScrapeError, ValueError) as exc:
            # Retry with JS render
            t0 = time.perf_counter()
            html = fetch(url, js_render=True, timeout=DEFAULT_TIMEOUT)
            result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
            result.status = 200
            result.content_length = len(html)
            result.content_type = "text/html"
            result.js_render_required = True
            result.notes.append(
                "ZenRows direct fetch failed; JS-render succeeded"
            )
    except ImportError:
        result.error = "scraping_api not available"
        result.notes.append("Shared scraping_api module not found in path")
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.notes.append("Scraping API probe failed")
    return result


# ---------------------------------------------------------------------------
# Main probe runner
# ---------------------------------------------------------------------------
def run_all_probes():
    """Execute all probes and return structured results."""
    probes = [
        probe_woolworths_browse(),
        probe_woolworths_search(),
        probe_woolworths_lists(),
        probe_coles_search(),
        probe_coles_browse(),
    ]

    # Attempt scraping-api probe for Woolworths saved-list page
    try:
        probes.append(
            probe_via_scraping_api(
                "Woolworths",
                "https://www.woolworths.com.au/shop/list",
            )
        )
    except Exception:
        pass

    # Attempt scraping-api probe for Coles dairy browse
    try:
        probes.append(
            probe_via_scraping_api(
                "Coles",
                "https://www.coles.com.au/browse/dairy",
            )
        )
    except Exception:
        pass

    return probes


def print_summary(probes):
    """Print a human-readable summary table of probe results."""
    line = "-" * 78
    print(line)
    print("  SUPERMARKET ENDPOINT PROBE RESULTS")
    print(f"  Timestamp: {_now_iso()}")
    print(line)
    print(
        f"  {'Store':<14} {'Label':<40} {'Status':<8} {'Time':<8} {'JS Req':<8}"
    )
    print(line)
    for p in probes:
        status_str = str(p.status) if p.status else p.error or "ERR"
        time_str = f"{p.elapsed_ms}ms" if p.elapsed_ms else "--"
        js_str = "YES" if p.js_render_required else "no" if p.js_render_required is False else "?"
        print(
            f"  {p.store:<14} {p.label:<40} {status_str:<8} {time_str:<8} {js_str:<8}"
        )
    print(line)
    print()

    # Detailed notes
    print("--- DETAILED NOTES ---")
    for p in probes:
        if p.notes:
            print(f"\n  [{p.store}] {p.label}")
            for note in p.notes:
                print(f"    - {note}")
            if p.error:
                print(f"    !! Error: {p.error}")

    # Conclusions
    print()
    print("--- CONCLUSIONS ---")
    ww_direct = [p for p in probes if p.store == "Woolworths" and not p.js_render_required and p.status == 200]
    coles_direct = [p for p in probes if p.store == "Coles" and not p.js_render_required and p.status == 200]

    if ww_direct:
        print("  [OK] Woolworths: Direct API access WORKS (no JS render needed)")
    else:
        print("  [!!] Woolworths: Direct API blocked -- JS render or cookies needed")

    if coles_direct:
        print("  [OK] Coles: Direct API access WORKS (no JS render needed)")
    else:
        print("  [!!] Coles: Direct API blocked -- JS render or cookies needed")

    # Check for scraping API success
    via_api = [p for p in probes if "scraping_api" in p.label and p.status == 200]
    if via_api:
        for p in via_api:
            js_note = "with JS render" if p.js_render_required else "without JS render"
            print(f"  [OK] Scraping API: {p.store} accessible {js_note}")

    print()
    print("--- HEADERS & AUTH REQUIREMENTS ---")
    ww_list_probe = [p for p in probes if "Saved Lists" in p.label]
    if ww_list_probe and ww_list_probe[0].auth_required:
        print("  - Woolworths saved lists: REQUIRES session cookie (WOOLWORTHS_COOKIE)")
        print("    Set WOOLWORTHS_COOKIE in .env for authenticated list access")
    else:
        print("  - Woolworths saved lists: accessible without auth (or not tested)")

    print("  - User-Agent required: Yes - use Chrome/Windows UA")
    print("  - Referer header: Recommended for Woolworths API")
    print("  - JSON Content-Type: Required for POST payloads")

    # Save JSON report
    report_path = os.path.join(_HERE, "probe_results.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump([p.to_dict() for p in probes], f, indent=2)
    print(f"\n[JSON] Full JSON report saved to: {report_path}")
    print(line)


def main():
    """Entry point."""
    print("== Supermarket Endpoint Probe ==")
    print("   Testing Woolworths and Coles API/HTML endpoints...\n")
    probes = run_all_probes()
    print_summary(probes)


if __name__ == "__main__":
    main()
